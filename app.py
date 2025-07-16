import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import openpyxl
import io
import time
import zipfile

### ------- UTILITY FUNCTIONS -------

PERIODICITY = {
    'Monthly': {
        'singular': 'month',
        'plural': 'months',
        'adj': 'monthly'
    },
    'Fortnightly': {
        'singular': 'fortnight',
        'plural': 'fortnights',
        'adj': 'fortnightly'
    },
    'Weekly': {
        'singular': 'week',
        'plural': 'weeks',
        'adj': 'weekly'
    }
}


def format_money_columns(df, cols):
    """
    Format specified numeric columns in a DataFrame to current strings.
    """
    for c in cols:
        df[c] = df[c].apply(lambda x: f"${x:,.2f}")
    return df

def show_interactive_chart(fig, chart_title="Chart", height=600):
    html_data = fig.to_html(include_plotlyjs='cdn')
    components.html(html_data, height=height)
    st.download_button(
        label=f"Download {chart_title} (HTML)",
        data=html_data,
        file_name=f"{chart_title.lower().replace(' ', '_')}.html",
        mime="text/html"
    )



def format_years_months(months):
    """Convert months to human-readable years+months."""
    years = months // 12
    months = months % 12
    if years and months:
        return f"{years} yr{'s' if years>1 else ''}, {months} mo"
    elif years:
        return f"{years} yr{'s' if years>1 else ''}"
    else:
        return f"{months} mo"


def periods_to_months(periods, frequency):
    if frequency == 'Monthly':
        return periods
    elif frequency == 'Fortnightly':
        return int(round(periods * 12 / 26))
    elif frequency == 'Weekly':
        return int(round(periods * 12 / 52))
    else:
        raise ValueError("Invalid frequency")


def period_label(frequency):
    return {
        'Monthly': 'month',
        'Fortnightly': 'fortnight',
        'Weekly': 'week'
    }[frequency]


def period_label_plural(frequency):
    return {
        'Monthly': 'months',
        'Fortnightly': 'fortnights',
        'Weekly': 'weeks'
    }[frequency]


def info_icon(text):
    st.markdown(f"❓ <span style='font-size: 0.9em; color: #666'>{text}</span>",
                unsafe_allow_html=True)


def money_fmt(x):
    return f"${x:,.2f}"


### ------- CALCULATION LOGIC -------


def show_interest_savings_message(extra,
                                  interest_saved,
                                  time_saved,
                                  frequency,
                                  label="Scenario A"):
    st.markdown(
        f"<div style='background-color:;padding:1em;border-radius:6px;'>"
        f"💡 <b>{label}</b>: By paying <b>${extra:,} extra</b> per {PERIODICITY[frequency]['singular']}, "
        f"you save <b>${interest_saved:,.2f}</b> in interest and cut <b>{format_years_months(int(time_saved))}</b> "
        f"{PERIODICITY[frequency]['plural']} off your loan."
        f"</div>",
        unsafe_allow_html=True)


def calculate_amort_schedule(principal,
                             annual_rate,
                             years,
                             months,
                             surplus,
                             frequency='Monthly',
                             redraw=0,
                             fees=0,
                             rate_changes=None,
                             baseline_interest_list=None):
    """
    Calculate amortisation, supporting extra repayments and rate changes.
    rate_changes = list of (start_month, new_rate)
    """
    freq_factor = dict(Monthly=12, Fortnightly=26, Weekly=52)[frequency]
    total_periods = years * freq_factor + months * (freq_factor // 12)
    period_rate = annual_rate / 100 / freq_factor
    loan_balance = float(principal)
    redraw_balance = float(redraw)
    accum_surplus = 0
    period = 0
    min_payment = None

    # Save for plotting
    history = []

    # Handle rate changes by month
    if not rate_changes: rate_changes = []
    rate_change_pointer = 0

    # Apply lump sum and fees to loan at month 0
    loan_balance += fees
    loan_balance -= redraw

    # Calculate baseline min payment:
    if period_rate == 0:
        baseline_min_payment = loan_balance / total_periods
    else:
        baseline_min_payment = (loan_balance * period_rate *
                                (1 + period_rate)**total_periods) / (
                                    (1 + period_rate)**total_periods - 1)

    while loan_balance > 0.01 and period < total_periods + 120:
        period += 1

        # Check for rate change
        if rate_change_pointer < len(rate_changes):
            change_period, new_rate = rate_changes[rate_change_pointer]
            if period >= change_period:
                period_rate = new_rate / 100 / freq_factor
                rate_change_pointer += 1

        periods_left = max(total_periods - (period - 1), 1)
        interest = loan_balance * period_rate

        # Min required this period for current loan balance
        if period_rate == 0:
            min_payment = min(loan_balance, loan_balance / periods_left)
        else:
            min_payment = min((loan_balance * period_rate *
                               (1 + period_rate)**periods_left) /
                              ((1 + period_rate)**periods_left - 1),
                              loan_balance + interest)
        principal_component = max(0, min_payment - interest)
        extra_payment = min(surplus, max(0,
                                         loan_balance - principal_component))
        total_paid = min_payment + extra_payment

        if baseline_interest_list is None:
            baseline_interest_list = [0.0] * total_periods  # or recalculate

        if len(baseline_interest_list) < period:
            interest_saved_this_period = 0.0
        else:
            interest_saved_this_period = baseline_interest_list[period -
                                                                1] - interest

        # Don't overpay loan:
        if loan_balance - (principal_component + extra_payment) < 0:
            overpay = -(loan_balance - (principal_component + extra_payment))
            extra_payment -= overpay
            total_paid -= overpay
            loan_balance = 0
        else:
            loan_balance -= (principal_component + extra_payment)

        redraw_balance += extra_payment
        accum_surplus += extra_payment

        #Compare to baseline interest
        if period - 1 < len(baseline_interest_list):
            interest_saved_this_period = baseline_interest_list[period -
                                                                1] - interest
        else:
            interest_saved_this_period = 0.0
        cumlative_interest_saved = (history[-1]['Cumulative Interest Saved']
                                    if period > 1 else
                                    0) + interest_saved_this_period

        history.append({
            'Month(s)':
            period,
            'Readable Date':
            format_years_months(period if frequency ==
                                'Monthly' else int(period / 12 * 12)),
            'Loan Balance':
            max(loan_balance, 0.0),
            'Payment':
            min_payment,
            'Interest':
            interest,
            'Principal Paid':
            principal_component,
            'Extra Payment':
            extra_payment,
            'Total Extra Paid':
            accum_surplus,
            'Redraw Remaining':
            redraw_balance,
            'Interest Rate':
            period_rate * freq_factor * 100,
            'Interest Saved This Month':
            interest_saved_this_period,
            'Cumulative Interest Saved':
            cumlative_interest_saved
        })
        if loan_balance <= 0.01:
            break
    df = pd.DataFrame(history)
    df.attrs['baseline_min_payment'] = baseline_min_payment
    df.attrs['total_periods'] = period
    return df


def df_to_csv_bytes(df):
    csv = df.to_csv(index=False)
    return csv.encode('utf-8')


def plot_schedule(df, label='Scenario', principal=None):
    fig = go.Figure()
    customdata = df[['Readable Date']].values
    fig.add_trace(
        go.Scatter(
            x=df['Readable Date'],
            y=df['Loan Balance'],
            name="Loan Balance",
            customdata=customdata,
            hovertemplate="%{customdata[0]}<br><b>$%{y:,.2f}</b><extra></extra>"
        ))

    fig.add_trace(
        go.Scatter(
            x=df['Readable Date'],
            y=df['Interest'].cumsum(),
            name='Cumulative Interest Paid',
            customdata=customdata,
            hovertemplate="%{customdata[0]}<br><b>$%{y:,.2f}</b><extra></extra>"
        ))

    fig.add_trace(
        go.Scatter(
            x=df['Readable Date'],
            y=df['Principal Paid'].cumsum(),
            name='Cumulative Principal Paid',
            customdata=customdata,
            hovertemplate="%{customdata[0]}<br><b>$%{y:,.2f}</b><extra></extra>"
        ))

    fig.update_layout(xaxis_title="Time (Years/Months)",
                      yaxis_title="Dollars",
                      title=f"Loan/Interest Over Time ({label})",
                      template="plotly_white")

    fig.update_yaxes(tickprefix='$', tickformat=',')
    if principal:
        fig.add_annotation(
            x=df['Readable Date'].iloc[0],
            y=df['Loan Balance'].iloc[0] + 10000,
            text="Loan starts here",
            showarrow=True,
            arrowhead=1,
            ax=10,
            ay=-20,
        )
    return fig


### ------- STREAMLIT INTERFACE -------

st.set_page_config(
    page_title="Mortgage Calculator", 
    page_icon='🏡',
    layout="wide",
    )

st.title("🔎🏡 Mortgage Calculator")

st.markdown("""
Welcome! This tool **simulates home loans**, helps you learn how repayments, interest, surplus payments, redraws, fees, and even rate changes affect your loan.
""")
with st.expander("📝 How to Use / What to Try"):
    st.markdown("""
1. Adjust loan details below. Hover over any <span style='color:#7bc'>? icon</span> for explanations!
2. Use **the extra payment slider** and see impact *instantly* on total time & interest.
3. (Advanced) Try toggling the **scenario comparison** or look at rate rise tests.
4. Download results (CSV, HTML or ZIP files) to keep learning, or explore the amortisation breakdown.
""",
                unsafe_allow_html=True)

st.header("📊 Upload Budget Sheet (Optional)")
error_message = '' 
uploaded_file = st.file_uploader(
    "Upload an Excel (.xlsx or .xls) budget file (with Income/Expenses/Surplus columns)",
    type=['xlsx', 'xls'],
    help=
    "Optional: Upload a budget Excel file with column headers like 'Income', 'Expenses', or 'Surplus' (case-insensitive)."
)

st.markdown(
    "You can simulate extra repayments using your real surplus/profit from your budget file."
)
st.markdown("---")

def match_col(cols, keyword):
    """
    Return first column containing the keyword (case-insensitive).
    """
    for c in cols:
        if keyword.lower() in c.lower():
            return c
    return None

budget_surplus = None
use_budget_surplus = False
error_message = None
surplus_col = None
budget_df = None

if uploaded_file is not None:
    try:
        budget_df = pd.read_excel(uploaded_file)
        cols = budget_df.columns

        # Find income, expense, surplus columns using your match_col function
        income_col = match_col(cols, "income")
        expense_col = match_col(cols, "expense")
        surplus_col = match_col(cols, "surplus")

        if surplus_col is None:
            # If surplus column missing, try to auto-calc surplus = income - expense
            if income_col and expense_col:
                budget_df["Surplus"] = budget_df[income_col] - budget_df[expense_col]
                surplus_col = "Surplus"
            else:
                error_message = (
                    "⚠️ Your budget sheet is missing required columns.\n\n"
                    "✅ Please make sure your Excel file includes at least columns with headers containing **Income** and **Expense**.\n"
                    "Column names are case-insensitive and partial matches like 'Monthly Income' or 'Living Expenses' work.\n\n"
                    "You can use the [example budget sheet](https://github.com/TheLastCodingMoose/Mortgage-Calculator/blob/main/budget_example.xlsx) as a template.\n\n"
                    "🔄 To reset, click the 'x' button above to remove the uploaded file."
                )
                budget_df = None

        if budget_df is not None and surplus_col:
            # Calculate average surplus (per row)
            avg_surplus = budget_df[surplus_col].mean()
            budget_surplus = max(0, int(avg_surplus))  # avoid negatives here

    except Exception as e:
        error_message = (
            f"❌ Failed to process your uploaded file.\n"
            "Make sure it's a valid Excel file (.xls or .xlsx) with Income and Expense columns.\n\n"
            f"Error details: {e}"
        )
        budget_df = None

    # Show upload result messages and preview
    if error_message:
        st.error(error_message)
    else:
        st.success("✅ Uploaded budget file successfully!")
        st.dataframe(budget_df, use_container_width=True)
        if surplus_col:
            st.info(
                f"Detected '{surplus_col}' column — Surplus will be taken as extra payment per period."
            )
            total_surplus = budget_df[surplus_col].sum()
            avg_surplus_display = budget_df[surplus_col].mean()
            st.write(f"**Total Surplus (sum):** ${total_surplus:,.2f}")
            st.write(f"**Average Surplus (per row):** ${avg_surplus_display:,.2f}")

else:
    use_budget_surplus = False

# Show checkbox if surplus is valid and no error
if budget_surplus is not None and budget_surplus >= 0 and not error_message:
    use_budget_surplus = st.checkbox(
        f"Use uploaded Surplus (${budget_surplus:,.2f} per period) as 'Extra Payment' in Scenario A?",
        value=True
    )
elif budget_surplus is not None and budget_surplus < 0:
    st.warning("⚠️ Your uploaded Surplus is negative. Extra payments will be set to $0.")


st.header("📘 Loan Inputs (Scenario A)")
colL, colR = st.columns(2)
with colL:
    principal = st.number_input(
        "💰 Loan Principal ($)",
        min_value=1000.0,
        value=500_000.0,
        step=1000.0,
        help=
        "The total loan amount you're borrowing from the bank (e.g., $500,000)."
    )
    info_icon("Borrowed home loan amount, e.g. $500,000")
    rate = st.number_input(
        "🎯 Interest rate (%)",
        min_value=0.01,
        value=5.0,
        step=0.01,
        help="The yearly interest rate applied to your loan(e.g., 5%).")
    info_icon("Annual interest rate (e.g. 5.2%).")
    years = st.number_input("⏳ Years", min_value=0, value=25, step=1)
    months = st.number_input("Months (additional)",
                             min_value=0,
                             max_value=11,
                             value=0,
                             step=1)
    freq = st.selectbox("Repayment Frequency",
                        ['Monthly', 'Fortnightly', 'Weekly'])
with colR:
    period_map = {
        'Monthly': 'per Month',
        'Fortnightly': 'per Fortnight',
        'Weekly': 'per Week'
    }

    if use_budget_surplus:
        surplus = int(budget_surplus)
        st.info(
            f"Extra Payment set from your budget upload: **${surplus:,.2f} per month**"
        )
    else:
        surplus = st.slider(
            f"💡 Extra Payment {period_map[freq]} ($)",
            0,
            20000,
            1000,
            100,
            help=
            "This is *extra* money you pay regularly in addition to required repayments. Try increasing this to see how much time and interest you can save!"
        )

    redraw = st.number_input(
        "🏦 Redraw Balance (Available Funds)",
        min_value=0.0,
        value=0.0,
        step=10000.0,
        help=
        "If you've already paid ahead, this is the extra balance available to redraw — treated as a lump sum prepayment."
    )
    fees = st.number_input(
        "🔖 One-Off Fees (e.g. LMI, Setup Costs)",
        min_value=0.0,
        value=0.0,
        step=100.0,
        help=
        "These are added to the loan balance at the start. Examples: Lender’s Mortgage Insurance (LMI), application fees."
    )
    ratetest = st.checkbox("Add Interest Rate Changes?")
    rate_changes = []
    if ratetest:
        steps = st.number_input(
            "How many changes?",
            1,
            5,
            1,
            help=
            "Tick this to add one or more interest rates changes (e.g. rate hikes) during the loan period."
        )
        for i in range(steps):
            col1, col2 = st.columns(2)
            with col1:
                step_month = st.number_input(
                    f'How many months? #{i+1})',
                    value=(i + 1) * 24,
                    min_value=1,
                    step=1,
                    key=f"change_month{i}",
                    help=
                    "When (in months) the interest rate will change, e.g. 24 = after 2 years."
                )
            with col2:
                new_rate = st.number_input(
                    f'New rate % at month {step_month}',
                    value=rate + 0.5 * (i + 1),
                    min_value=0.01,
                    step=0.01,
                    key=f"change_rate{i}",
                    help=
                    "The new interest rate that will apply from that month onwards."
                )

            periods_per_year = dict(Monthly=12, Fortnightly=26,
                                    Weekly=52)[freq]
            period_num = int(round((step_month / 12.0) * periods_per_year))
            rate_changes.append((period_num, new_rate))

comparison = st.checkbox("Compare to a Second Scenario?")
if comparison:
    st.markdown("---")
    st.header("📕 Loan Inputs (Scenario B)")
    colL2, colR2 = st.columns(2)
    with colL2:
        principal_b = st.number_input("💰 Loan Principal ($) - B",
                                      min_value=1000.0,
                                      value=principal,
                                      step=10000.0,
                                      key="pB", 
                                     help=
                                         "The total loan amount you're borrowing from the bank (e.g., $500,000)."
                                     )
        info_icon("Borrowed home loan amount, e.g. $500,000")
        rate_b = st.number_input(
            "🎯 Interest rate (%) - B",
            min_value=0.01,
            value=rate,
            step=0.01,
            key="rB",
            help="Interest rate for the Scenario B loan, used for comparison.")
        info_icon("❓ Annual interest rate (e.g. 5.2%).")
        years_b = st.number_input("⏳ Years - B",
                                  min_value=0,
                                  value=years,
                                  step=1,
                                  key="yB")
        months_b = st.number_input("Months (additional) - B",
                                   min_value=0,
                                   max_value=11,
                                   value=months,
                                   step=1,
                                   key="mB")
        freq_b = st.selectbox("Repayment Frequency - B",
                              ['Monthly', 'Fortnightly', 'Weekly'],
                              index=['Monthly', 'Fortnightly',
                                     'Weekly'].index(freq),
                              key="frB")
    with colR2:
        period_map = {
            'Monthly': 'per Month',
            'Fortnightly': 'per Fortnight',
            'Weekly': 'per Week'
        }

        if use_budget_surplus:
            surplus_b = int(budget_surplus)
            st.info(
                f"Extra Payment set from your budget upload: **${surplus:,.2f} per month**"
            )
        else:
            surplus_b = st.slider(
                f"💡 Extra Payment {period_map[freq_b]}",
                0,
                20000,
                surplus,
                100,
                key="spB",
                help=
                "This is *extra* money you pay regularly in addition to required repayments. Try increasing this to see how much time and interest you can save!"
            )

        redraw_b = st.number_input("🏦 Redraw Balance (Available Funds) - B",
                                   min_value=0.0,
                                   value=redraw,
                                   step=10000.0,
                                   key="lsB", help=
                                       "If you've already paid ahead, this is the extra balance available to redraw — treated as a lump sum prepayment."
                                   )

        fees_b = st.number_input("🔖 One-Off Fees (e.g. LMI, Setup Costs) - B",
                                 min_value=0.0,
                                 value=fees,
                                 step=100.0,
                                 key="feesB",
                                    help=
                                    "These are added to the loan balance at the start. Examples: Lender’s Mortgage Insurance (LMI), application fees."
                                )
        ratetestB = st.checkbox("Add Interest Rate Changes? - B", key="rcB")
        rate_changes_b = []
        if ratetestB:
            stepsB = st.number_input(
                "How many changes? (B)",
                1,
                5,
                1,
                key="stpB",
                help='Month into loan when the rate changes')
            for i in range(stepsB):
                sm = st.number_input(
                    f'When? (B, #{i+1})',
                    value=(i + 1) * 24,
                    min_value=1,
                    step=1,
                    key=f"cmonB{i}",
                    help="Month into loan when the rate changes")
                nr = st.number_input(f'New rate % at month {sm} (B)',
                                     value=rate_b + 0.5 * (i + 1),
                                     min_value=0.01,
                                     step=0.01,
                                     key=f"crB{i}")
                periods_per_year_b = dict(Monthly=12,
                                          Fortnightly=26,
                                          Weekly=52)[freq_b]
                period_num_b = int(round((sm / 12.0) * periods_per_year_b))
                rate_changes_b.append((period_num_b, nr))

if years == 0 and months == 0:
    st.error("Loan term must be at least 1 month.")
    st.stop()

if st.button('Run Loan Simulation 🚀'):
    # Generate baseline(no extra payment), just get interest per period
    baseline_schedule = calculate_amort_schedule(principal,
                                                 rate,
                                                 years,
                                                 months,
                                                 0,
                                                 frequency=freq,
                                                 redraw=redraw,
                                                 fees=fees,
                                                 rate_changes=rate_changes,
                                                 baseline_interest_list=[])
    baseline_interest_list = list(baseline_schedule['Interest'])

    # --- Scenario A ---
    df = calculate_amort_schedule(
        principal,
        rate,
        years,
        months,
        surplus,
        frequency=freq,
        redraw=redraw,
        fees=fees,
        rate_changes=rate_changes,
        baseline_interest_list=baseline_interest_list)

    st.toast("✅ Scenario A Complete.")

    min_repay = df.attrs['baseline_min_payment']
    total_interest = df['Interest'].sum()
    months_to_pay = df['Month(s)'].iloc[-1]
    total_extra_paid = df['Total Extra Paid'].iloc[-1]
    # Calculate months equivalent, depending on frequency
    if freq == 'Monthly':
        total_months = months_to_pay
    elif freq == 'Fortnightly':
        total_months = int(round(months_to_pay * 12 / 26))
    elif freq == 'Weekly':
        total_months = int(round(months_to_pay * 12 / 52))
    else:
        total_months = months_to_pay  # fallback, should not happen

    loan_period_text = format_years_months(total_months)

    st.markdown("---")
    st.subheader("Results: Scenario A")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Minimum payment per month", f"🏦 ${min_repay:,.2f}")
        info_icon("What the bank requires you to pay, not counting extra.")
    with col2:
        st.metric("Total interest paid", f"💸 ${total_interest:,.2f}")
        info_icon("Sum of all interest paid to the bank over the loan.")
    with col3:
        st.metric("Loan paid off in", f"💰 {loan_period_text}")
        info_icon("How long until the loan is 100% cleared.")

    # -- Popups --
    baseline_df = calculate_amort_schedule(principal,
                                           rate,
                                           years,
                                           months,
                                           0,
                                           frequency=freq,
                                           redraw=redraw,
                                           fees=fees,
                                           rate_changes=rate_changes)
    interest_saved = baseline_df['Interest'].sum() - total_interest
    time_saved = baseline_df.attrs['total_periods'] - months_to_pay
    time_saved_text = format_years_months(int(time_saved))

    show_interest_savings_message(surplus,
                                  interest_saved,
                                  time_saved,
                                  freq,
                                  label="Scenario A")

    # --- Charts ---
    fig_a = plot_schedule(df, "Scenario A", principal=principal)
    st.plotly_chart(fig_a, use_container_width=True, key='aa')

    # Scenario A - interactive HTML export + download + display 
    html_a = fig_a.to_html(full_html=False)
    st.download_button(
        label="📈 Download Line Graph A (HTML)",
        data=html_a,
        file_name="Scenario_A_Line_Chart.html",
        mime="text/html"
    )

    # Pie chart: Interest/Principal (Scenario A)
    pies = go.Figure(data=[
        go.Pie(labels=['Interest', 'Principal', 'Surplus'],
               values=[total_interest, principal, total_extra_paid],
               hole=0.45,
                marker=dict(colors=['#ff2b2b', '#0068c9', '#83c9ff'])  # Set colours explicitly
              )
    ])

    pies.update_traces(
        textinfo='label+percent',
        pull=[0.05, 0.02, 0.02],
        hovertemplate=
        '%{label}: <b>$%{value:,.2f}</b> (<b>%{percent} </b>)<extra></extra>')

    pies.update_layout(title="Scenario A – Where does your money go?",
                       legend_title_text='Loan Components',
                       showlegend=False)

    st.plotly_chart(pies, use_container_width=True, key='ac')

    try:
        img_bytes = pies.to_html(full_html=False)
        st.download_button(
            label="🥧 Download Pie Chart (HTML)",
            data=img_bytes,
            file_name="Pie Chart A.html",
            mime="text/html"
            )
    except Exception as e:
        st.warning("Could not download Pie Chart. Please try again.")

    # --- Table (preview, with highlight) ---
    st.subheader("Key Points & Table")

    money_cols = [
        'Loan Balance', 'Payment', 'Interest', 'Principal Paid',
        'Extra Payment', 'Interest Saved This Month',
        'Cumulative Interest Saved'
    ]

    df_display = format_money_columns(df.copy(), money_cols)

    st.data_editor(df_display[[
        'Readable Date', 'Loan Balance', 'Payment', 'Interest',
        'Principal Paid', 'Extra Payment', 'Interest Saved This Month',
        'Cumulative Interest Saved'
    ]],
                   use_container_width=True,
                   disabled=True,
                   key='editorA')

    # --- Download options ---
    st.download_button("📊 Download Table Results (CSV)",
                       df_to_csv_bytes(df),
                       file_name="Table Results A.csv",
                       mime="text/csv")

    # --- Scenario B (optional comparison) ---
    if comparison:
        if years_b == 0 and months_b == 0:
            st.error("scenario B: Loan term must be at least 1 month.")
            st.stop()

        # Generate the baseline schedule for Scenario B (no extra payments).
        baseline_schedule_b = calculate_amort_schedule(
            principal_b,
            rate_b,
            years_b,
            months_b,
            0,
            frequency=freq_b,
            redraw=redraw_b,
            fees=fees_b,
            rate_changes=rate_changes_b)
        baseline_interest_list_b = list(baseline_schedule_b['Interest'])

        df_b = calculate_amort_schedule(
            principal_b,
            rate_b,
            years_b,
            months_b,
            surplus_b,
            frequency=freq_b,
            redraw=redraw_b,
            fees=fees_b,
            rate_changes=rate_changes_b,
            baseline_interest_list=baseline_interest_list_b)

        time.sleep(0.3)
        st.toast("✅ Scenario B complete")

        min_repay_b = df_b.attrs['baseline_min_payment']
        total_interest_b = df_b['Interest'].sum()
        months_to_pay_b = df_b['Month(s)'].iloc[-1]
        total_extra_paid_b = df_b['Total Extra Paid'].iloc[-1]
        loan_period_text_b = format_years_months(
            months_to_pay_b if freq_b ==
            "Monthly" else int(months_to_pay_b //
                               (12 / (12 if freq_b == "Monthly" else 1))))
        baseline_df_b = calculate_amort_schedule(principal_b,
                                                 rate_b,
                                                 years_b,
                                                 months_b,
                                                 0,
                                                 frequency=freq_b,
                                                 redraw=redraw_b,
                                                 fees=fees_b,
                                                 rate_changes=rate_changes_b)
        interest_saved_b = baseline_df_b['Interest'].sum() - total_interest_b
        time_saved_b = baseline_df_b.attrs['total_periods'] - months_to_pay_b

        # Calculate months equivalent (for _b), depending on frequency
        if freq_b == 'Monthly':
            total_months_b = months_to_pay_b
        elif freq_b == 'Fortnightly':
            total_months_b = int(round(months_to_pay_b * 12 / 26))
        elif freq_b == 'Weekly':
            total_months_b = int(round(months_to_pay_b * 12 / 52))
        else:
            total_months_b = months_to_pay_b  # fallback, should not happen

        comp_metrics = [
            ("Minimum Payment", f"🏦 {money_fmt(min_repay)}",
             f"🏦 {money_fmt(min_repay_b)}"),
            ("Total Interest Paid", f"💸 {money_fmt(total_interest)}",
             f"💸 {money_fmt(total_interest_b)}"),
            ("Loan Paid Off In", f"💰 {format_years_months(total_months)}",
             f"💰 {format_years_months(total_months_b)}"),
            ("Interest Saved", f"🏆 {money_fmt(interest_saved)}",
             f"🏆 {money_fmt(interest_saved_b)}"),
            ("Time Saved", f"⏳ {format_years_months(int(time_saved))}",
             f"⏳ {format_years_months(int(time_saved_b))}"),
            ("Total Surplus in Account", f"📈 {money_fmt(total_extra_paid)}",
             f"📈 {money_fmt(total_extra_paid_b)}")
        ]

        comp = pd.DataFrame(comp_metrics,
                            columns=["Metric", "Scenario A", "Scenario B"])

        # Convert the DataFrame to a downloadable CSV format
        st.markdown("---")
        st.subheader("Results: Scenario B")

        col1b, col2b, col3b = st.columns(3)
        with col1b:
            st.metric("Minimum payment per month", f"🏦 ${min_repay_b:,.2f}")
            info_icon("What the bank requires you to pay, not counting extra.")
        with col2b:
            st.metric("Total interest paid", f"💸 ${total_interest_b:,.2f}")
            info_icon("Sum of all interest paid to the bank over the loan.")

        with col3b:
            st.metric("Loan paid off in",
                      f"💰 {format_years_months(total_months_b)}")
            info_icon("How long until the loan is 100% cleared.")

        periodicity = {
            'Monthly': 'month',
            'Fortnightly': 'fortnight',
            'Weekly': 'week'
        }
        periodicity_plural = {
            'Monthly': 'months',
            'Fortnightly': 'fortnights',
            'Weekly': 'weeks'
        }

        time_saved_text_b = format_years_months(int(time_saved_b))
        show_interest_savings_message(surplus_b,
                                      interest_saved_b,
                                      time_saved_b,
                                      freq_b,
                                      label="Scenario B")

        fig_b = plot_schedule(df_b, "Scenario B", principal=principal_b)
        st.plotly_chart(fig_b, use_container_width=True, key='ad')

        # Scenario B - interactive HTML export + download + display
        html_b = fig_b.to_html(full_html=False)
        st.download_button(
            label="📉 Download Line Graph B (HTML)",
            data=html_b,
            file_name="Line Graph B.html",
            mime="text/html"
        )


        # Pie chart: Interest/Principal (Scenario B)
        pies_b = go.Figure(data=[
            go.Pie(labels=['Interest', 'Principal', 'Surplus'],
                   values=[total_interest_b, principal_b, total_extra_paid_b],
                   hole=0.45,
                   marker=dict(colors=['#ff2b2b', '#0068c9', '#83c9ff'])  # Match colours
                   )
        ])
        pies_b.update_traces(
            textinfo='label+percent',
            pull=[0.05, 0.02, 0.02],
            hovertemplate=
            '%{label}: <b>$%{value:,.2f}</b> (<b>%{percent} </b>)<extra></extra>'
        )

        pies_b.update_layout(title="Scenario B – Where does your money go?",
                             showlegend=False)
        st.plotly_chart(pies_b, use_container_width=True, key='af')
        img_bytes = pies_b.to_html(full_html=False)
        st.download_button(
            label="🥧 Download Pie Chart B (HTML)",
            data=img_bytes,
            file_name="Pie Chart B.html",
            mime="text/html"
            )

        # --- Key Points & Table for Scenario B ---
        st.subheader("Key Points & Table: Scenario B")

        money_cols_b = [
            'Loan Balance', 'Payment', 'Interest', 'Principal Paid',
            'Extra Payment', 'Interest Saved This Month',
            'Cumulative Interest Saved'
        ]

        # Format the Scenario B data
        df_display_b = format_money_columns(df_b.copy(), money_cols_b)

        # Display the formatted dataframe (Scenario B)
        st.data_editor(df_display_b[[
            'Readable Date', 'Loan Balance', 'Payment', 'Interest',
            'Principal Paid', 'Extra Payment', 'Interest Saved This Month',
            'Cumulative Interest Saved'
        ]],
                       use_container_width=True,
                       disabled=True,
                       key='editorB')

        # Add a download button for Scenario B data
        st.download_button("📊 Download Table Results B (CSV)",
                           df_to_csv_bytes(df_b),
                           file_name="Table Results B.csv",
                           mime="text/csv")

        st.header("📊 Scenario Comparison Table (A vs. B)")
        st.dataframe(comp, use_container_width=True)

        def comparison_table_to_csv_bytes(df):
            csv = df.to_csv(index=False)  # Convert DataFrame to CSV string
            return csv.encode('utf-8')  # Encode as bytes

        comp_formatted = comp.copy()
        # Add the download button
        st.download_button(label="💹 Download (A vs. B) Comparison Table (CSV)",
                           data=comparison_table_to_csv_bytes(comp_formatted),
                           file_name="(A vs. B) Comparison Table.csv",
                           mime="text/csv")

        # Build ZIP file of all outputs
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a") as zip_file:

            zip_file.writestr("scenario_a_line_chart.html", fig_a.to_html(full_html=True))
            zip_file.writestr("scenario_b_line_chart.html", fig_b.to_html(full_html=True))
            zip_file.writestr("pie_chart_a.html", pies.to_html(full_html=True))
            zip_file.writestr("pie_chart_b.html", pies_b.to_html(full_html=True))
            zip_file.writestr("amortisation_A.csv", df_to_csv_bytes(df))
            zip_file.writestr("amortisation_B.csv", df_to_csv_bytes(df_b))
            zip_file.writestr("scenario_comparison_table.csv", comparison_table_to_csv_bytes(comp))

        st.markdown("---")
        # Prepare download button
        zip_buffer.seek(0)
        st.download_button(
            label="📦 Download All Charts and Tables (ZIP)",
            data=zip_buffer,
            file_name="All Charts and Tables.zip",
            mime="application/zip"
        )

        st.info(
            "Every table and chart is downloadable."
            "\n\n💾 Downloadable Table  =  Download CSV"
            "\n\n📈 Downloadable Pie/Line Graph  =  Go to Graph → HTML download"
            "\n\n💽 Download All = Download ZIP File",
            icon="📥")

        if st.button("⬆️ Back to Top"):
            st.experimental_rerun()

st.markdown("---")
st.markdown(
    """Created by Jake Mottershead
    \n\n 🔗 GitHub: (https://github.com/TheLastCodingMoose) 
    \n\n 📬 Feedback or bugs? [Open an issue](https://github.com/TheLastCodingMoose/mortgage-calculator/issues) 
    \n\n 🛠️ Version: **v1.0.0** – Last updated: July 2025""",
    unsafe_allow_html=True)
