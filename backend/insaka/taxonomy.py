"""Transaction categories shared by the generator, the labeller and the evaluation."""

CATEGORIES = {
    "customer_payment": "Money received from a customer for goods or services",
    "cash_deposit": "Business takings deposited as cash",
    "own_account_transfer": "Moving money between the owner's own bank and wallet accounts",
    "input_purchase": "Payment to a supplier for stock, seed, fertiliser, feed, fuel, spares "
                      "or other business inputs",
    "wages": "Pay for workers",
    "rent": "Rent for premises",
    "utilities": "Electricity (ZESCO) and water",
    "airtime_data": "Airtime and data bundles",
    "family_transfer": "Money sent to relatives",
    "school_fees": "School fees",
    "loan_repayment": "Repayment of an existing loan",
    "tax_payment": "Payment to ZRA",
    "bank_charges": "Bank and mobile-money fees and interest",
    "cash_withdrawal": "Cash taken out at an ATM or agent",
    "other": "Anything that fits no other category",
}

# Categories that count as business income when computing features.
INCOME_CATEGORIES = ("customer_payment", "cash_deposit")

CHANNELS = ("absa", "mtn", "airtel")
