"""Business types the generator draws from. All supplier names are fictional."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Archetype:
    key: str
    label: str
    sector: str              # "agriculture" or "sme"
    season: str              # key into calendar.SEASONAL
    income_range: tuple      # typical monthly takings in kwacha (low, high)
    ticket: float            # typical customer payment in kwacha
    cogs_ratio: tuple        # share of takings paid to suppliers (low, high)
    momo_share: tuple        # share of takings that arrive by mobile money (low, high)
    suppliers: tuple
    name_suffixes: tuple


ARCHETYPES = (
    Archetype("maize_trader", "Maize trader", "agriculture", "harvest", (6_000, 60_000), 450,
              (0.55, 0.70), (0.45, 0.80),
              ("Eastern Grain Haulage", "Mtendere Grain Bags", "Luangwa Transporters"),
              ("Grain Traders", "Maize Trading", "Agro Trading")),
    Archetype("input_dealer", "Agro-input dealer", "agriculture", "inputs", (10_000, 120_000), 700,
              (0.60, 0.75), (0.35, 0.70),
              ("Kafue Seed Distributors", "Copperhill Fertiliser Wholesale", "Agri-Chem Supplies Zambia"),
              ("Agro Inputs", "Farm Supplies", "Agro Dealers")),
    Archetype("smallholder", "Smallholder farmer", "agriculture", "harvest", (3_000, 18_000), 900,
              (0.30, 0.45), (0.50, 0.85),
              ("Kafue Seed Distributors", "Village Fert Agent", "Tiyende Tractor Hire"),
              ("Farm", "Farming", "Farms")),
    Archetype("poultry", "Poultry farmer", "agriculture", "retail", (5_000, 45_000), 250,
              (0.55, 0.70), (0.55, 0.85),
              ("Hatchwell Day-Old Chicks", "Mpongwe Feeds", "Vet-Care Agrovet"),
              ("Poultry", "Poultry Farm", "Broilers")),
    Archetype("horticulture", "Vegetable grower", "agriculture", "dry_season", (4_000, 25_000), 200,
              (0.35, 0.50), (0.55, 0.85),
              ("Greenleaf Seedlings", "DripPro Irrigation", "Vet-Care Agrovet"),
              ("Gardens", "Fresh Produce", "Horticulture")),
    Archetype("retail_shop", "Grocery shop", "sme", "retail", (8_000, 150_000), 120,
              (0.65, 0.80), (0.40, 0.75),
              ("Tiyanjane Wholesale", "Kanyama Cash & Carry", "Northern Beverages Depot"),
              ("General Dealers", "Grocery", "Shop")),
    Archetype("market_stall", "Market trader", "sme", "retail", (3_000, 20_000), 60,
              (0.60, 0.75), (0.55, 0.90),
              ("Soweto Market Wholesalers", "City Market Suppliers", "Tiyanjane Wholesale"),
              ("Trading", "Market Stand", "Enterprises")),
    Archetype("salon", "Hair salon", "sme", "retail", (4_000, 30_000), 150,
              (0.30, 0.45), (0.55, 0.90),
              ("Glamour Beauty Wholesale", "Hairline Imports", "Kanyama Cash & Carry"),
              ("Salon", "Beauty Parlour", "Hair Studio")),
    Archetype("tailor", "Tailor", "sme", "uniforms", (3_000, 18_000), 250,
              (0.40, 0.55), (0.50, 0.85),
              ("Kamwala Fabrics", "Chitenge House", "Needlecraft Supplies"),
              ("Tailoring", "Designs", "Fashions")),
    Archetype("hardware", "Hardware store", "sme", "dry_season", (15_000, 250_000), 900,
              (0.65, 0.80), (0.25, 0.55),
              ("Cement & Steel Distributors", "Roofing Sheets Zambia", "BuildMart Wholesale"),
              ("Hardware", "Building Supplies", "Hardware & General")),
    Archetype("transport", "Minibus operator", "sme", "flat", (8_000, 60_000), 300,
              (0.40, 0.55), (0.45, 0.80),
              ("Fuel Point Service Station", "Spares Corner Motors", "Tyre World Zambia"),
              ("Transport", "Logistics", "Bus Services")),
    Archetype("restaurant", "Eatery", "sme", "flat", (6_000, 70_000), 80,
              (0.50, 0.65), (0.50, 0.85),
              ("Kanyama Cash & Carry", "Mpongwe Feeds", "Northern Beverages Depot"),
              ("Restaurant", "Eatery", "Kitchen")),
)

BY_KEY = {a.key: a for a in ARCHETYPES}

# Mwila's business is a mix of two archetypes, so she gets her own.
MWILA_ARCHETYPE = Archetype(
    "maize_and_inputs", "Maize and inputs trader", "agriculture", "maize_and_inputs",
    (18_000, 18_000), 500, (0.58, 0.58), (0.55, 0.55),
    ("Chipata Agro Inputs", "Eastern Grain Haulage"), ("Maize & Inputs",),
)

# Fictional lenders, schools and landlords for recurring payments.
LENDERS = ("Kwacha Microfinance", "Tiyende Credit", "Mapalo Lending")
SCHOOLS = ("Hillview Primary School", "Mapalo Academy", "Sunrise Secondary School",
           "Chimwemwe Basic School", "Lake View College")
LANDLORDS = ("Mwanza Properties", "Kalulu Estates", "Phiri Shops Rentals", "Town Council Market")
