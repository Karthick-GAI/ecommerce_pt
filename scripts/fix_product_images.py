"""
fix_product_images.py — Update product images to use category-relevant photos.

Uses loremflickr.com which returns images by keyword. The `lock` param ensures
each product always gets the same image (deterministic by product id hash).
"""

import os
import hashlib
import psycopg2

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgre_catalogue"
)

# Maps (category, subcategory) → loremflickr keyword(s)
CATEGORY_KEYWORDS = {
    # Electronics
    ("Electronics", "Smartphone"):              "smartphone,phone",
    ("Electronics", "Laptop"):                  "laptop,computer",
    ("Electronics", "Headphones & Earphones"):  "headphones,earphones",
    ("Electronics", "Tablet"):                  "tablet,ipad",
    ("Electronics", "Camera"):                  "camera,photography",
    ("Electronics", "TV"):                      "television,screen",
    ("Electronics", "Smartwatch"):              "smartwatch,wearable",

    # Clothing
    ("Clothing", "Men's T-Shirts"):             "tshirt,menswear",
    ("Clothing", "Men's Formal Shirts"):        "shirt,formal",
    ("Clothing", "Men's Footwear"):             "shoes,sneakers",
    ("Clothing", "Men's Jeans"):                "jeans,denim",
    ("Clothing", "Men's Jackets"):              "jacket,coat",
    ("Clothing", "Women's Tops"):               "blouse,women",
    ("Clothing", "Women's Dresses"):            "dress,fashion",
    ("Clothing", "Women's Kurtas"):             "kurta,ethnicwear",
    ("Clothing", "Women's Footwear"):           "heels,womenshoes",
    ("Clothing", "Women's Sarees"):             "saree,ethnic",

    # Beauty
    ("Beauty", "Skincare"):                     "skincare,moisturizer",
    ("Beauty", "Makeup"):                       "makeup,cosmetics",
    ("Beauty", "Haircare"):                     "haircare,shampoo",
    ("Beauty", "Fragrance"):                    "perfume,fragrance",

    # Books
    ("Books", "Fiction"):                       "book,novel,reading",
    ("Books", "Finance"):                       "book,finance,money",
    ("Books", "Self-Help"):                     "book,motivation",
    ("Books", "Technology"):                    "book,technology,programming",
    ("Books", "Children"):                      "childrens-book,reading",

    # Sports & Fitness
    ("Sports & Fitness", "Protein Powder"):     "protein,supplement,fitness",
    ("Sports & Fitness", "Yoga"):               "yoga,mat,exercise",
    ("Sports & Fitness", "Running"):            "running,shoes,jogging",
    ("Sports & Fitness", "Gym Equipment"):      "gym,dumbbell,fitness",
    ("Sports & Fitness", "Cricket"):            "cricket,bat,sport",

    # Baby Products
    ("Baby Products", "Baby Toys"):             "baby,toy,infant",
    ("Baby Products", "Baby Clothing"):         "baby,clothing,infant",
    ("Baby Products", "Baby Care"):             "baby,care,bottle",

    # Stationery
    ("Stationery", "Office Essentials"):        "stationery,pen,office",
    ("Stationery", "Notebooks"):                "notebook,journal,stationery",

    # Toys & Games
    ("Toys & Games", "Educational"):            "toy,education,learning",
    ("Toys & Games", "Board Games"):            "boardgame,chess,family",
    ("Toys & Games", "Action Figures"):         "toy,action-figure",

    # Home & Kitchen (fallbacks)
    ("Home & Kitchen", "Cookware"):             "cookware,kitchen,pan",
    ("Home & Kitchen", "Appliances"):           "appliance,kitchen",
    ("Home & Kitchen", "Furniture"):            "furniture,home",
    ("Home & Kitchen", "Decor"):                "homedecor,decor",
}

# Category-level fallbacks (when subcategory has no specific mapping)
CATEGORY_FALLBACKS = {
    "Electronics":      "electronics,gadget",
    "Clothing":         "fashion,clothing",
    "Beauty":           "beauty,cosmetics",
    "Books":            "book,reading",
    "Sports & Fitness": "fitness,sport",
    "Baby Products":    "baby,infant",
    "Stationery":       "stationery,office",
    "Toys & Games":     "toy,game",
    "Home & Kitchen":   "kitchen,home",
    "Food & Grocery":   "food,grocery",
    "Automotive":       "car,automotive",
    "Health":           "health,medicine",
}


def image_url(product_id: str, keywords: str) -> str:
    lock = int(hashlib.md5(product_id.encode()).hexdigest(), 16) % 100_000
    return f"https://loremflickr.com/800/600/{keywords}?lock={lock}"


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("SELECT id, category, subcategory FROM products WHERE is_active = TRUE")
    rows = cur.fetchall()
    print(f"Updating images for {len(rows)} products...")

    updated = 0
    for product_id, category, subcategory in rows:
        keywords = (
            CATEGORY_KEYWORDS.get((category, subcategory))
            or CATEGORY_FALLBACKS.get(category)
            or "product,shopping"
        )
        url = image_url(product_id, keywords)

        # Update primary_image on products table
        cur.execute(
            "UPDATE products SET primary_image = %s WHERE id = %s",
            (url, product_id)
        )

        # Update the primary image row in product_images table
        cur.execute(
            "UPDATE product_images SET url = %s WHERE product_id = %s AND is_primary = TRUE",
            (url, product_id)
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done. Updated {updated} products.")


if __name__ == "__main__":
    main()
