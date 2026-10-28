"""Sitemap, robots.txt and OG image generation for search engine crawlers.

Public and read-only. The sitemap enumerates every auto-generated SEO page —
HSN/GST rate pages and GSTIN lookup pages — alongside the static tool pages,
so crawlers discover them without following links through JavaScript.

The OG image endpoint renders a branded 1200x630 PNG with Pillow so every
page can carry a unique social preview without shipping pre-built images.
"""
from __future__ import annotations

import io
import textwrap
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from PIL import Image, ImageDraw, ImageFont

from app.core.rate_limit import RateLimit

router = APIRouter(tags=["health"])

_seo_limit = RateLimit("seo_sitemap", "30/minute", by="ip")

SITE = "https://gst.doaide.com"

STATIC_PAGES = [
    "/",
    "/calculator",
    "/lookup",
    "/hsn",
    "/due-dates",
    "/resources",
    "/pricing",
    "/penalty-calculator",
    "/eway-bill",
    "/input-tax-credit",
    "/composition-scheme",
    "/invoice-generator",
    "/reverse-charge",
    "/reverse-gst-calculator",
    "/itc-mismatch",
    "/filing-checklist",
    "/gstr3b-reconciliation",
    "/whatsapp",
    "/blog",
    "/blog/gst-filing-guide-india-2026",
    "/blog/hsn-code-lookup",
    "/blog/gst-compliance-checklist-small-business",
    "/blog/gstr-9-annual-return-fy-2025-26-guide",
    "/blog/gst-invoice-management-system-ims-guide",
    "/blog/gst-invoice-format-guide-2026",
]

HSN_CODES = [
    "0101", "0102", "0105", "0106", "0201", "0202", "0203", "0204", "0207", "0208",
    "0210", "0301", "0302", "0303", "0304", "0305", "0306", "0307", "0401", "0402",
    "0403", "0404", "0405", "0406", "0407", "0408", "0409", "0410", "0504", "0505",
    "0511", "0601", "0602", "0603", "0604", "0701", "0702", "0703", "0704", "0706",
    "0707", "0708", "0709", "0710", "0712", "0713", "0801", "0802", "0803", "0804",
    "0805", "0806", "0807", "0808", "0809", "0810", "0811", "0813", "0901", "0902",
    "0903", "0904", "0905", "0906", "0907", "0908", "0909", "0910", "1001", "1002",
    "1003", "1004", "1005", "1006", "1007", "1008", "1101", "1102", "1103", "1104",
    "1105", "1106", "1107", "1108", "1201", "1202", "1205", "1206", "1207", "1209",
    "1210", "1211", "1212", "1301", "1302", "1401", "1404", "1501", "1502", "1504",
    "1507", "1508", "1509", "1510", "1511", "1512", "1513", "1514", "1515", "1516",
    "1517", "1518", "1520", "1521", "1601", "1602", "1604", "1605", "1701", "1702",
    "1703", "1704", "1801", "1803", "1804", "1805", "1806", "1901", "1902", "1903",
    "1904", "1905", "2001", "2002", "2003", "2004", "2005", "2006", "2007", "2008",
    "2009", "2101", "2102", "2103", "2104", "2105", "2106", "2201", "2202", "2203",
    "2204", "2207", "2209", "2301", "2302", "2304", "2306", "2309", "2401", "2402",
    "2403", "2501", "2505", "2506", "2510", "2515", "2516", "2517", "2521", "2523",
    "2601", "2602", "2603", "2606", "2701", "2702", "2704", "2706", "2710", "2711",
    "2713", "2801", "2803", "2804", "2806", "2807", "2811", "2814", "2815", "2836",
    "2901", "2902", "2905", "2915", "2933", "2936", "2937", "2941", "3001", "3002",
    "3003", "3004", "3005", "3006", "3101", "3102", "3103", "3104", "3105", "3201",
    "3204", "3205", "3206", "3207", "3208", "3209", "3210", "3213", "3214", "3215",
    "3301", "3302", "3303", "3304", "3305", "3306", "3307", "3401", "3402", "3403",
    "3405", "3406", "3501", "3503", "3506", "3604", "3605", "3701", "3702", "3802",
    "3808", "3814", "3822", "3826", "3901", "3902", "3903", "3904", "3906", "3907",
    "3909", "3917", "3918", "3919", "3920", "3921", "3922", "3923", "3924", "3925",
    "3926", "4001", "4002", "4008", "4009", "4010", "4011", "4012", "4013", "4014",
    "4015", "4016", "4101", "4104", "4107", "4201", "4202", "4203", "4205", "4301",
    "4303", "4401", "4403", "4407", "4408", "4410", "4411", "4412", "4415", "4418",
    "4419", "4421", "4601", "4602", "4801", "4802", "4804", "4808", "4810", "4811",
    "4817", "4818", "4819", "4820", "4821", "4901", "4902", "5001", "5004", "5007",
    "5201", "5204", "5205", "5208", "5209", "5210", "5303", "5305", "5310", "5402",
    "5407", "5503", "5509", "5512", "5513", "5601", "5603", "5607", "5608", "5701",
    "5702", "5703", "5903", "6001", "6101", "6102", "6103", "6104", "6105", "6106",
    "6107", "6108", "6109", "6110", "6111", "6112", "6114", "6115", "6116", "6201",
    "6202", "6203", "6204", "6205", "6206", "6207", "6208", "6209", "6211", "6212",
    "6213", "6214", "6215", "6301", "6302", "6303", "6304", "6305", "6306", "6307",
    "6401", "6402", "6403", "6404", "6405", "6406", "6505", "6506", "6601", "6602",
    "6702", "6704", "6801", "6802", "6806", "6809", "6810", "6813", "6901", "6902",
    "6904", "6905", "6906", "6907", "6910", "6911", "6912", "6913", "7005", "7007",
    "7009", "7010", "7013", "7016", "7017", "7019", "7101", "7102", "7103", "7104",
    "7106", "7108", "7110", "7113", "7114", "7115", "7117", "7118", "7201", "7202",
    "7204", "7207", "7208", "7209", "7210", "7211", "7212", "7213", "7214", "7215",
    "7216", "7217", "7219", "7222", "7225", "7228", "7301", "7304", "7305", "7306",
    "7307", "7308", "7309", "7310", "7311", "7312", "7313", "7314", "7315", "7317",
    "7318", "7320", "7321", "7322", "7323", "7324", "7326", "7403", "7404", "7407",
    "7408", "7411", "7418", "7601", "7604", "7606", "7607", "7608", "7610", "7615",
    "7616", "7801", "7901", "8001", "8201", "8202", "8203", "8204", "8205", "8207",
    "8211", "8212", "8213", "8215", "8301", "8302", "8303", "8305", "8306", "8309",
    "8311", "8402", "8407", "8408", "8409", "8411", "8413", "8414", "8415", "8418",
    "8419", "8421", "8422", "8423", "8424", "8426", "8427", "8429", "8432", "8433",
    "8436", "8437", "8438", "8443", "8446", "8450", "8452", "8462", "8465", "8467",
    "8471", "8473", "8474", "8477", "8479", "8481", "8482", "8483", "8501", "8502",
    "8503", "8504", "8505", "8506", "8507", "8508", "8509", "8510", "8511", "8512",
    "8513", "8515", "8516", "8517", "8518", "8519", "8521", "8523", "8525", "8526",
    "8527", "8528", "8529", "8531", "8532", "8534", "8535", "8536", "8537", "8539",
    "8541", "8542", "8544", "8601", "8603", "8605", "8606", "8607", "8608", "8609",
    "8701", "8702", "8703", "8704", "8706", "8707", "8708", "8711", "8712", "8713",
    "8714", "8716", "8801", "8802", "8803", "8804", "8901", "8902", "8903", "8904",
    "8905", "8907", "9001", "9002", "9003", "9004", "9005", "9006", "9011", "9015",
    "9017", "9018", "9021", "9022", "9025", "9026", "9027", "9028", "9030", "9031",
    "9032", "9101", "9102", "9103", "9105", "9111", "9113", "9201", "9202", "9205",
    "9206", "9207", "9209", "9301", "9303", "9304", "9306", "9401", "9402", "9403",
    "9404", "9405", "9406", "9503", "9504", "9505", "9506", "9507", "9601", "9603",
    "9606", "9607", "9608", "9609", "9611", "9613", "9615", "9617", "9619", "9954",
    "9961", "9962", "9963", "9964", "9965", "9966", "9967", "9968", "9969", "9970",
    "9971", "9972", "9973", "9974", "9975", "9976", "9977", "9978", "9979", "9980",
    "9981", "9982", "9983", "9984", "9985", "9986", "9987", "9988", "9989", "9990",
    "9991", "9992", "9993", "9994", "9995", "9996", "9997", "9998",
]

PRODUCT_SLUGS = [
    "rice", "wheat", "wheat-flour", "atta", "sugar", "milk", "tea", "coffee",
    "dal", "lentils", "biscuits", "bread", "chocolate", "soft-drinks",
    "cold-drinks", "cola", "bottled-water", "mineral-water", "cement",
    "medicine", "medicines", "drugs", "toothpaste", "shampoo", "soap",
    "detergent", "paint", "plastic-bags", "plastic-bottles", "tyres", "tires",
    "books", "newspapers", "cotton-fabric", "silk-fabric", "t-shirts",
    "shirts", "jeans", "trousers", "dresses", "shoes", "footwear", "sandals",
    "ceramic-tiles", "tiles", "marble", "granite", "gold-jewellery",
    "silver-jewellery", "jewellery", "steel", "iron", "air-conditioner", "ac",
    "refrigerator", "fridge", "washing-machine", "laptop", "computer",
    "desktop", "printer", "mobile-phone", "smartphone", "phone", "headphones",
    "earphones", "speaker", "television", "tv", "monitor", "led-bulb", "car",
    "motor-car", "suv", "motorcycle", "bike", "scooter", "bicycle",
    "spectacles", "sunglasses", "glasses", "furniture", "chair", "sofa",
    "table", "desk", "mattress", "toys", "pen", "pencil", "diapers",
    "sanitary-pads", "it-services", "consulting", "software-services",
    "legal-services", "accounting-services", "ca-services",
    "construction-services", "cab", "taxi", "uber", "ola", "freight",
    "courier", "education", "tuition", "hospital", "healthcare", "insurance",
    "banking", "gym", "salon", "laundry", "rent", "oil", "cooking-oil",
    "sunflower-oil", "palm-oil", "soybean-oil", "potato", "tomato",
    "vegetables", "cheese", "paneer", "ghee", "butter", "curd", "yogurt",
    "cream", "honey", "eggs", "chicken", "mutton", "fish", "prawns", "shrimp",
    "onion", "garlic", "ginger", "turmeric", "spices", "chilli", "pepper",
    "salt", "jaggery", "maida", "semolina", "suji", "noodles", "pasta",
    "chips", "namkeen", "papad", "pickles", "jam", "ketchup", "sauce",
    "ice-cream", "juice", "fruit-juice", "coconut-oil", "mustard-oil",
    "cigarettes", "tobacco", "petrol", "diesel", "lpg", "natural-gas",
    "perfume", "deodorant", "cosmetics", "lipstick", "face-cream",
    "sunscreen", "hair-oil", "conditioner", "hand-wash", "sanitizer",
    "disinfectant", "mosquito-repellent", "fertilizer", "pesticide",
    "pvc-pipe", "plastic-sheet", "rubber", "handbag", "wallet", "belt",
    "suitcase", "backpack", "paper", "notebook", "diary", "cardboard-box",
    "tissue-paper", "saree", "kurta", "salwar", "jacket", "sweater", "socks",
    "undergarments", "towel", "bedsheet", "curtain", "carpet", "rug",
    "helmet", "cap", "hat", "umbrella", "bricks", "cement-blocks",
    "sanitary-ware", "glass", "mirror", "gold", "silver", "diamond",
    "platinum", "stainless-steel", "aluminium", "copper", "brass",
    "steel-pipe", "steel-rod", "tmt-bar", "nuts-and-bolts", "wire", "nail",
    "lock", "fan", "ceiling-fan", "water-heater", "geyser", "iron-box",
    "mixer-grinder", "microwave", "oven", "water-purifier", "inverter", "ups",
    "battery", "solar-panel", "cable", "switch", "cctv-camera", "router",
    "tablet", "ipad", "pen-drive", "hard-disk", "keyboard", "mouse",
    "projector", "camera", "smartwatch", "watch", "wristwatch",
    "electric-vehicle", "ev", "auto-rickshaw", "tractor", "truck", "bus",
    "ambulance", "stethoscope", "wheelchair", "hearing-aid", "contact-lens",
    "bed", "wardrobe", "dining-table", "bookshelf", "lamp", "chandelier",
    "pillow", "cricket-bat", "football", "badminton-racket", "chess",
    "video-game", "playing-cards", "doll", "board-game", "eraser", "stapler",
    "scissors", "tape", "glue", "hotel-room", "restaurant-food", "catering",
    "movie-ticket", "event-ticket", "security-services", "cleaning-services",
    "transport", "logistics", "warehousing", "advertising", "web-development",
    "app-development", "cloud-hosting", "internet", "broadband",
    "mobile-recharge", "electricity", "real-estate", "flat", "apartment",
    "life-insurance", "health-insurance", "motor-insurance", "mutual-fund",
    "stock-broking", "chartered-accountant", "audit-services",
    "architect-services", "photography", "printing-services",
    "courier-services", "dry-cleaning", "tailoring", "beauty-parlour", "spa",
    "yoga-classes", "coaching", "training",
]

def _build_sitemap() -> str:
    today = date.today().isoformat()
    urls = []

    for page in STATIC_PAGES:
        urls.append(
            f"  <url><loc>{SITE}{page}</loc>"
            f"<changefreq>weekly</changefreq>"
            f"<priority>0.8</priority></url>"
        )

    for code in HSN_CODES:
        urls.append(
            f"  <url><loc>{SITE}/hsn/{code}</loc>"
            f"<lastmod>{today}</lastmod>"
            f"<changefreq>monthly</changefreq>"
            f"<priority>0.7</priority></url>"
        )

    for slug in PRODUCT_SLUGS:
        urls.append(
            f"  <url><loc>{SITE}/gst-rate/{slug}</loc>"
            f"<lastmod>{today}</lastmod>"
            f"<changefreq>monthly</changefreq>"
            f"<priority>0.7</priority></url>"
        )

    body = "\n".join(urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>"
    )


ROBOTS_TXT = f"""\
User-agent: *
Allow: /
Allow: /gst-rate/
Allow: /gstin/
Allow: /calculator
Allow: /lookup
Allow: /hsn
Allow: /hsn/
Allow: /due-dates
Allow: /resources
Allow: /pricing
Allow: /penalty-calculator
Allow: /eway-bill
Allow: /input-tax-credit
Allow: /composition-scheme
Allow: /invoice-generator
Allow: /reverse-charge
Allow: /itc-mismatch
Allow: /blog/

Disallow: /api/
Disallow: /invoices
Disallow: /upload
Disallow: /reconcile
Disallow: /itc$
Disallow: /filing$
Disallow: /suppliers
Disallow: /alerts
Disallow: /usage
Disallow: /status

Sitemap: {SITE}/api/v1/seo/sitemap.xml
"""


@router.get(
    "/seo/sitemap.xml",
    summary="XML sitemap for search engine crawlers",
    description=(
        "Lists all public pages — static tool pages, auto-generated HSN/GST "
        "rate pages, and GSTIN lookup pages — for crawler discovery."
    ),
    dependencies=[Depends(_seo_limit)],
)
def sitemap() -> Response:
    return Response(
        content=_build_sitemap(),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get(
    "/seo/robots.txt",
    summary="Robots.txt for search engine crawlers",
    dependencies=[Depends(_seo_limit)],
)
def robots() -> Response:
    return Response(
        content=ROBOTS_TXT,
        media_type="text/plain",
        headers={"Cache-Control": "public, max-age=86400"},
    )


_og_limit = RateLimit("seo_og_image", "60/minute", by="ip")

_OG_WIDTH = 1200
_OG_HEIGHT = 630
_BG_COLOR = (37, 99, 235)  # #2563EB
_TEXT_COLOR = (255, 255, 255)
_WATERMARK_COLOR = (255, 255, 255, 153)  # 60% opacity white


def _wrap_text(text: str, max_chars: int = 35) -> list[str]:
    return textwrap.wrap(text, width=max_chars) or [""]


def _render_og_image(title: str, subtitle: str | None = None) -> bytes:
    img = Image.new("RGB", (_OG_WIDTH, _OG_HEIGHT), _BG_COLOR)
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        watermark_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except OSError:  # IOError is an alias of OSError
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        watermark_font = ImageFont.load_default()

    title_lines = _wrap_text(title, max_chars=30)
    line_height = 64
    total_height = len(title_lines) * line_height
    if subtitle:
        total_height += 60

    y = (_OG_HEIGHT - total_height) // 2 - 30

    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        w = bbox[2] - bbox[0]
        draw.text(((_OG_WIDTH - w) // 2, y), line, fill=_TEXT_COLOR, font=title_font)
        y += line_height

    if subtitle:
        sub_lines = _wrap_text(subtitle, max_chars=50)
        y += 20
        for line in sub_lines[:2]:
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            w = bbox[2] - bbox[0]
            draw.text(
                ((_OG_WIDTH - w) // 2, y),
                line, fill=_WATERMARK_COLOR, font=subtitle_font,
            )
            y += 38

    watermark = "doaide.com"
    bbox = draw.textbbox((0, 0), watermark, font=watermark_font)
    w = bbox[2] - bbox[0]
    draw.text(
        ((_OG_WIDTH - w) // 2, _OG_HEIGHT - 60),
        watermark, fill=_WATERMARK_COLOR, font=watermark_font,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get(
    "/seo/og-image",
    summary="Dynamic Open Graph image",
    description=(
        "Renders a branded 1200x630 PNG for social sharing previews. "
        "Pass title and optional subtitle as query params."
    ),
    dependencies=[Depends(_og_limit)],
)
def og_image(
    title: str = Query(..., min_length=1, max_length=200),
    subtitle: str | None = Query(None, max_length=300),
) -> Response:
    png = _render_og_image(title, subtitle)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
