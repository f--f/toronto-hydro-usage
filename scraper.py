"""Scrape Toronto Hydro usage data."""
import requests
import lxml.html
from urllib.parse import urljoin


LOGIN_URL = r"https://css.torontohydro.com/selfserve/pages/login.aspx?ReturnUrl=%2f_layouts%2fAuthenticate.aspx%3fSource%3d%252f&Source=%2f"
USAGE_URL = r"https://css.torontohydro.com/Pages/ICFRedirect.aspx?Controller=myenergy&Action=billhistory"
DATA_URL = r"https://myusage.torontohydro.com/cassandra/getfile/period/all/format/csv"
# Toronto Hydro's SSL is misconfigured (intermediate certificates aren't sent by the server: https://www.ssllabs.com/ssltest/analyze.html?d=css.torontohydro.com
# So the certificate chain is bundled here.
CA_BUNDLE = "torontohydro_cert_bundle.pem"


def extract_formdata(res, form_selector="*", 
input_extractors=None):
    """Extract form data generically from HTML content."""
    tree = lxml.html.fromstring(res.content)
    forms = tree.xpath(f"//form[{form_selector}]")
    assert len(forms) == 1, "Number of forms selected not equal to 1."
    form = forms[0]
    inputs = form.xpath(f"//input")
    formdata = {ele.name: ele.value for ele in inputs}
    formattr = dict(form.attrib)
    if "action" in formattr:  # make action an absolute URL
        formattr["action"] = urljoin(res.url, formattr["action"])
    # Optionally extract fields of interest
    if input_extractors is None:
        return formattr, formdata
    else:
        extracted_fields = {}
        for key, extract in input_extractors.items():
            extracted_fields[key] = [ele for ele in inputs if extract(ele)]
        return formattr, formdata, extracted_fields


def submit_redirect_form(formattr, formdata, session=requests):
    """Submit a form. Meant for forms where the response redirects the page (and a lack of redirect indicates failure)."""
    res = session.request(formattr["method"], formattr["action"], data=formdata)
    if res.url == formattr["action"]:
        raise ValueError("Form submission unsuccessful: expected page redirect.")
    return session, res


def get_login_form(username, password):
    """Retrieve form data entries from login page.
    This can be requested statelessly."""
    res = requests.get(LOGIN_URL, verify=CA_BUNDLE)

    extract_fields = {
        "username": lambda ele: ele.type == "text",
        "password": lambda ele: ele.type == "password"
    }
    formattr, formdata, fields = extract_formdata(
        res, "@name='aspnetForm'", extract_fields)
    # Test that form contains expected number of login/password fields
    assert (len(fields["username"]) == 1 and 
        len(fields["password"]) == 1 and
        len(formdata) > 2), f"Unexpected number of form fields at {LOGIN_URL}"
    # Substitute username and password into form
    formdata[fields["username"][0].name] = username
    formdata[fields["password"][0].name] = password
    return formattr, formdata


def get_hydro_usage(username, password):
    loginattr, logindata = get_login_form(username, password)

    with requests.Session() as session:
        try:
            session.verify = CA_BUNDLE
            # Authenticate on the main login page
            # (This provides the cookies for accessing the usage page)
            session, _ = submit_redirect_form(loginattr, logindata, session)
            # Authenticate on the usage page
            # (Accessing the usage page returns a JS-based redirect with a dynamically-generated form that needs to be submitted to get another set of authentication cookies for accessing the data...)
            res = session.get(USAGE_URL)
            formattr, formdata = extract_formdata(res, "@name='form'")
            session, res = submit_redirect_form(formattr, formdata, session)
            # Finally, access the CSV data
            res = session.get(DATA_URL)
        except requests.exceptions.SSLError as e:
            print(e)
