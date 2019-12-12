import os
from io import StringIO

import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import holidays  # For time-of-use categorization

from scraper import get_hydro_usage

# TODO:
# Historical weather (hourly) is available from: Intl Airport
# This returns data for the month (Day is arbitrary), so need to call multiple times
# Ideally should cache historical data, this isn't really too many API calls
# https://climate.weather.gc.ca/climate_data/bulk_data_e.html?format=csv&stationID=51459&Year=2002&Month=12&Day=31&timeframe=1&submit=Download+Data

ONTARIO_HOLIDAYS = holidays.Canada(prov="ON")

try:
    USERNAME = os.environ["TORONTOHYDRO_USERNAME"]
    PASSWORD = os.environ["TORONTOHYDRO_PASSWORD"]
except KeyError as e:
    print(
        ("Must specify username and password using the environment variables "),
        ("TORONTOHYDRO_USERNAME and TORONTOHYDRO_PASSWORD.")
    )
    raise e


def get_time_of_use_period(dt: pd.Timestamp) -> str:
    """Return a string corresponding to the time-of-use category for the
    datetime."""
    # 7PM - 7AM, weekends, and holidays are always off-peak
    if (dt.weekday() >= 5 or 
        not(7 <= dt.hour < 12+7) or
        dt in ONTARIO_HOLIDAYS): 
        return "Off-peak"
    # Nov - Apr is winter, versus May-Oct for summer
    is_winter = dt.month in (11, 12, 1, 2, 3, 4)
    # On-peak and off-peak switch between winter and summer
    if (7 <= dt.hour < 11) or (12+5 <= dt.hour < 12+7):
        return "On-peak" if is_winter else "Mid-peak"
    elif 11 <= dt.hour < 12+5:
        return "Mid-peak" if is_winter else "On-peak"
    else:
        assert False, "Time of use inference error."  # should never occur!


@st.cache
def load_data(username: str, password: str) -> pd.DataFrame:
    """Returns Toronto Hydro electricity data for the given credentials."""
    csv_data = get_hydro_usage(username, password).text
    df = pd.read_csv(StringIO(csv_data), 
                     usecols=["Date", "Cost", "Quantity"],
                     parse_dates=["Date"])
    # Data is in local time (switches EST/EDT). At the switch (e.g. Nov 3 2019 1AM), the
    # duration is 7200 (likely comprising data from both EST and EDT timezones).
    # pandas has issues infering the timezone for this so just arbitrarily set it to EST
    df.Date = df.Date.dt.tz_localize("US/Eastern", 
                                     ambiguous=np.zeros(len(df)).astype(bool))
    # Infer time-of-use (off-peak, mid-peak, on-peak)
    df["Time-of-use"] = df["Date"].apply(get_time_of_use_period)
    return df


@st.cache(ignore_hash=True)
def generate_chart(df, yaxis, timeunit) -> alt.Chart:
    """Return an Altair chart with usage data."""
    print(timeunit)
    chart = alt.Chart(df)
    palette = alt.Color("Time-of-use:N",
        scale=alt.Scale(domain=["On-peak", "Mid-peak", "Off-peak"],
                        range=["#cb5b29", "#fac90a", "#98c23c"]))
    if timeunit is not None:
        chart = chart.transform_timeunit(
            as_="Time", field="Date", timeUnit=timeunit,
        ).transform_aggregate(
            Quantity="sum(Quantity)", 
            Cost="sum(Cost)",
            groupby=["Time", "Time-of-use"]
        ).mark_bar().encode(
            x=alt.X("Time:T", timeUnit=timeunit),
            y=alt.Y(f"{yaxis[0]}:Q", title=f"{yaxis[0]} ({yaxis[1]})"),
            color=palette,
            tooltip=["Time:T", "Cost:Q", "Quantity:Q"]
        )
    else:
        chart = chart.mark_bar().encode(
            x="Date:T",
            y=alt.Y(f"{yaxis[0]}:Q", title=f"{yaxis[0]} ({yaxis[1]})"),
            color=palette,
            tooltip=["Date:T", "Cost:Q", "Quantity:Q"]
        )
    chart = chart.properties(height=400).interactive(bind_y=False)
    return chart


def main() -> None:
    """Main execution of Streamlit app."""
    df = load_data(USERNAME, PASSWORD)

    st.title("Toronto Hydro Electricity Usage")
    st.markdown("Visualizes data from Toronto Hydro usage.")
    if st.checkbox("Show DataFrame"):
        st.dataframe(df)

    # Sidebar options
    yaxis = st.sidebar.radio("Which quantity to plot on the vertical axis?", 
        (("Cost", "$"), ("Quantity", "kW h")), 
        format_func=lambda y: f"{y[0]} ({y[1]})")
    timeperiod = st.sidebar.radio("In what intervals should time be binned?",
        ("Hourly", "Daily", "Monthly", "Yearly"))
    to_timeunit = {
        "Hourly": None,
        "Daily": "yearmonthdate",
        "Monthly": "yearmonth",
        "Yearly": "year",
    }

    chart = generate_chart(df, yaxis, to_timeunit[timeperiod])
    st.altair_chart(chart)


if __name__ == "__main__":
    main()