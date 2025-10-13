# A simple, durable SKU format

**Format (15–18 chars w/ hyphens for readability):**  
`CAT-SUB-SRC-SZ-COL-CND-SEQ`

- **CAT** (2): category
  
  - UG = undergarments, CW = cold-weather, CG = camping, AC = accouterments

- **SUB** (2–3): subcategory
  
  - TP = top, BT = bottom, SK = socks, GL = gloves, HT = hats, BG = bags, SL = sleep, SH = shelter, KT = kit

- **SRC** (2): source
  
  - DR = DRMO/Defense surplus, LC = local commercial

- **SZ** (2–3): size
  
  - XS, S, M, L, XL, 2X, 3X, numeric (e.g., 07, 08 for gloves/boots)

- **COL** (2–3): color/pattern
  
  - BK = black, OD = olive drab, CY = coyote, FG = foliage, MC = multicam, TN = tan, GN = green, MX = mixed/assorted

- **CND** (1): condition grade (internal)
  
  - N = new, A = excellent, B = good, C = fair, D = rough

- **SEQ** (3): unique base-36 counter per subfamily (000–ZZZ)

Store without hyphens in your system if you want compact codes; print with hyphens for humans.

## Examples

- `UG-TP-DR-M-OD-B-0F7` → surplus wicking T-shirt, Medium, Olive Drab, Grade B

- `CW-GL-DR-L-OD-A-01C` → surplus fleece gloves, Large, OD, Grade A

- `CG-SL-LC-REG-TN-N-00K` → commercial sleeping bag, Regular, Tan, New

- `AC-BG-DR-NA-MC-B-02P` → surplus assault bag, Multicam, no size, Grade B

- `CG-KT-DR-NA-MX-B-001` → surplus mess kit bundle, mixed colors, Grade B

> **Tip:** Use `NA` for size when not applicable. For bundles/kits use `KT`.

# Why this works for mixed surplus + retail

- **Source-aware** (DR vs LC) without burying purchase details in the code.

- **Condition-proof**: you can regrade without renumbering—only the `CND` changes.

- **Short + readable**: staff can decode at a glance, but the real details live in your item record.

- **Expandable**: add a new SUB or color code without breaking old SKUs.

# What *not* to encode

- Don’t cram **full NSNs**, vendor names, costs, or dates into the SKU. Put those in fields:
  
  - `nsn` (full), `upc/ean` (if retail item has one), `brand`, `style`, `acq_date`, `cost`, `lot_id`, `notes`.

# Database fields (minimal set)

- `sku` (unique), `title/description`, `category`, `subcategory`, `source`, `size`, `color`, `condition_grade`, `nsn` (if present), `upc` (if retail), `brand`, `material`, `notes`, `bin_location`, `qty_on_hand`, `cost`, `price`, `images`.

# Barcodes & scanning

- **Internal:** print your SKU in **Code 128** (great for alphanumerics).

- **External retail:** if a commercial item already has a **UPC/EAN/GTIN**, store it and label the shelf/tag with both your SKU and the UPC. For pure surplus without UPC, your Code 128 is enough.

# Special cases you’ll hit (and how to handle them)

- **One-of-a-kind surplus lots:** same base SKU with different `SEQ` per unit; stash lot notes in `lot_id`.

- **Mixed sizes in one bag:** create separate SKUs per size, or mark size `MX` only if truly assorted and sold as a single mixed bundle.

- **Color variants within camo families:** keep `MC` generic unless shoppers care about sub-patterns; if they do, extend to `MC1/MC2` or add an attribute field rather than lengthening the SKU.

- **Kits/Bundles:** prefix SUB with `KT` and list components in the item’s `bundle_components` field; price and track as one SKU.

# Starter code lists you can copy

**Categories (CAT):** UG, CW, CG, AC  
**Undergarments (SUB):** TP (tops), BT (bottoms), SK (socks)  
**Cold-weather (SUB):** GL (gloves), HT (hats), TP (tops), BT (bottoms)  
**Camping (SUB):** SL (sleep systems), SH (shelter), BG (bags), KT (kit)  
**Accouterments (SUB):** BG (bags/pouches), BLT (belts), CV (covers), PS (patches)

**Colors (COL):** BK, OD, CY, FG, MC, TN, GN, GR, MX  
(You can keep this list short and map “Coyote Brown”, “Coyote Tan” → `CY` in your system.)

# Quick validation rules

- Fixed pattern: `^[A-Z]{2}-[A-Z]{2,3}-[A-Z]{2}-[A-Z0-9]{2,3}-[A-Z]{2,3}-[A-Z]{1}-[0-9A-Z]{3}$`

- Case: uppercase only; avoid O/0 and I/1 in `SEQ`.

- Guarantee uniqueness on (`CAT`,`SUB`,`SRC`,`SZ`,`COL`,`CND`,`SEQ`).

---
