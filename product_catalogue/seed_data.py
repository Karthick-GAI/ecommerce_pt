#!/usr/bin/env python3
"""
seed_data.py — Populate PostgreSQL + pgvector with sample product data.

Usage:
    python3 seed_data.py              # seed all products
    python3 seed_data.py --reset      # DROP tables, recreate, then seed
"""
import argparse
import random
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

from database import engine, Base, SessionLocal
from models import Product, ProductImage, Review, Category
from sqlalchemy import text as sql_text

# ── CATALOGUE ─────────────────────────────────────────────────────────────────
# Each entry: (name, description, specs_dict, tags_list, brand, base_price_inr)

CATALOGUE = {
    "Electronics": {
        "Laptop": [
            ("Apple MacBook Air M3 13-inch",
             "Superfast Apple M3 chip, 18-hour battery life, completely fanless. Thin and light — perfect for students and professionals.",
             {"Display": "13.6-inch Liquid Retina", "Chip": "Apple M3", "RAM": "8GB", "Storage": "256GB SSD", "Battery": "18 hr", "Weight": "1.24 kg"},
             ["macOS", "fanless", "ultrabook", "long battery", "lightweight"], "Apple", 89990),

            ("Apple MacBook Pro M3 14-inch",
             "Professional-grade M3 Pro chip with Liquid Retina XDR display. Built for video editing, 3D rendering, and Xcode.",
             {"Display": "14.2-inch Liquid Retina XDR", "Chip": "Apple M3 Pro", "RAM": "18GB", "Storage": "512GB SSD", "Battery": "18 hr"},
             ["pro", "M3 Pro", "developer", "creative", "Xcode"], "Apple", 149990),

            ("Dell XPS 15 OLED",
             "15.6-inch 3.5K OLED display, Intel Core i7-13700H. The premium Windows laptop for creative professionals.",
             {"Display": "15.6-inch OLED 3.5K", "Processor": "Intel Core i7-13700H", "RAM": "16GB DDR5", "Storage": "512GB SSD", "Battery": "13 hr"},
             ["oled", "premium", "4K", "creative", "Windows"], "Dell", 115990),

            ("Dell Inspiron 15 3000",
             "Reliable everyday laptop for home and college. AMD Ryzen 5 processor, Full HD display, great value for money.",
             {"Display": "15.6-inch FHD", "Processor": "AMD Ryzen 5 5500U", "RAM": "8GB", "Storage": "512GB SSD"},
             ["college", "budget", "everyday", "AMD", "home"], "Dell", 45990),

            ("HP Pavilion 15 Laptop",
             "AMD Ryzen 5 IPS display, ideal for students and office work at a comfortable price.",
             {"Display": "15.6-inch FHD IPS", "Processor": "AMD Ryzen 5 5500U", "RAM": "8GB", "Storage": "512GB SSD", "Battery": "8 hr"},
             ["student", "office", "IPS", "AMD", "value"], "HP", 43990),

            ("HP Envy x360 14 2-in-1",
             "Convertible 2-in-1 with OLED display, Intel Core i5, stylus support. Works as laptop and tablet.",
             {"Display": "14-inch 2.8K OLED", "Processor": "Intel Core i5-1335U", "RAM": "16GB", "Storage": "512GB SSD", "Type": "2-in-1"},
             ["2-in-1", "convertible", "touch", "OLED", "stylus"], "HP", 79990),

            ("Lenovo IdeaPad Slim 5",
             "Thin and light 14-inch laptop with Intel Core i5. Great portability for students who are always on the move.",
             {"Display": "14-inch FHD IPS", "Processor": "Intel Core i5-1335U", "RAM": "8GB", "Storage": "512GB SSD", "Battery": "10 hr", "Weight": "1.46 kg"},
             ["slim", "student", "lightweight", "Intel", "portable"], "Lenovo", 49990),

            ("Lenovo ThinkPad E14 Gen 5",
             "Business laptop with AMD Ryzen 7, MIL-SPEC durability, and ThinkPad's legendary keyboard.",
             {"Display": "14-inch FHD IPS", "Processor": "AMD Ryzen 7 7730U", "RAM": "16GB", "Storage": "512GB SSD", "MIL-SPEC": "Yes"},
             ["business", "durable", "Ryzen", "ThinkPad", "professional"], "Lenovo", 64990),

            ("Asus VivoBook 16X OLED",
             "16-inch 2.8K OLED panel, Ryzen 7. Large display for multimedia and creative tasks.",
             {"Display": "16-inch 2.8K OLED", "Processor": "AMD Ryzen 7 7730U", "RAM": "16GB", "Storage": "512GB SSD", "Battery": "12 hr"},
             ["oled", "large screen", "AMD", "multimedia", "creator"], "Asus", 64990),

            ("Asus ROG Strix G15",
             "High-performance gaming laptop with Ryzen 9, RTX 4060 GPU, and 144Hz display. Dominate every game.",
             {"Display": "15.6-inch FHD 144Hz", "Processor": "AMD Ryzen 9 7945HX", "GPU": "RTX 4060", "RAM": "16GB", "Storage": "1TB SSD"},
             ["gaming", "RTX", "144Hz", "RGB", "Ryzen 9"], "Asus", 119990),
        ],
        "Smartphone": [
            ("Apple iPhone 15 128GB",
             "A16 Bionic chip, Dynamic Island, 48MP main camera, USB-C. The benchmark for premium smartphones.",
             {"Display": "6.1-inch Super Retina XDR", "Chip": "A16 Bionic", "Storage": "128GB", "Camera": "48MP + 12MP", "Battery": "3349 mAh", "5G": "Yes"},
             ["5G", "Dynamic Island", "iOS", "USB-C", "premium"], "Apple", 69990),

            ("Apple iPhone 15 Plus 256GB",
             "Bigger 6.7-inch screen, all-day battery, A16 Bionic chip. Ideal for users who want more screen real estate.",
             {"Display": "6.7-inch Super Retina XDR", "Chip": "A16 Bionic", "Storage": "256GB", "Battery": "4383 mAh", "5G": "Yes"},
             ["5G", "large screen", "iOS", "long battery", "USB-C"], "Apple", 84990),

            ("Samsung Galaxy S24 5G 128GB",
             "Snapdragon 8 Gen 3, Galaxy AI features, 50MP triple camera, 7 years of Android updates.",
             {"Display": "6.2-inch Dynamic AMOLED 2X", "Processor": "Snapdragon 8 Gen 3", "RAM": "8GB", "Storage": "128GB", "Camera": "50MP Triple", "Battery": "4000 mAh"},
             ["AI", "5G", "AMOLED", "Galaxy", "premium"], "Samsung", 74999),

            ("Samsung Galaxy A55 5G",
             "Mid-range powerhouse: AMOLED display, 50MP OIS camera, 5000 mAh battery. Best Samsung mid-ranger.",
             {"Display": "6.6-inch Super AMOLED", "Processor": "Exynos 1480", "RAM": "8GB", "Storage": "128GB", "Camera": "50MP OIS", "Battery": "5000 mAh"},
             ["5G", "mid-range", "AMOLED", "OIS", "long battery"], "Samsung", 34999),

            ("OnePlus 12R 5G 128GB",
             "Snapdragon 8 Gen 1, 100W SUPERVOOC charging, Sony 50MP camera. Fast charging king.",
             {"Display": "6.74-inch AMOLED 120Hz", "Processor": "Snapdragon 8 Gen 1", "RAM": "8GB", "Storage": "128GB", "Camera": "50MP Sony", "Battery": "5000 mAh", "Charging": "100W"},
             ["fast charging", "5G", "Snapdragon", "gaming", "OnePlus"], "OnePlus", 39999),

            ("Redmi Note 13 Pro 5G 256GB",
             "108MP camera with OIS, 67W turbo charging, Dimensity 7200-Ultra. Best camera phone in the budget segment.",
             {"Display": "6.67-inch AMOLED 120Hz", "Processor": "Dimensity 7200-Ultra", "RAM": "8GB", "Storage": "256GB", "Camera": "108MP OIS", "Battery": "5100 mAh"},
             ["camera", "5G", "budget", "OIS", "AMOLED"], "Redmi", 29999),

            ("Realme Narzo 60 Pro 5G",
             "Dimensity 7050, 100W charging, 100MP camera, smooth AMOLED display. Incredible value for budget buyers.",
             {"Display": "6.7-inch AMOLED 120Hz", "Processor": "Dimensity 7050", "RAM": "8GB", "Storage": "128GB", "Camera": "100MP", "Battery": "4880 mAh", "Charging": "100W"},
             ["budget", "fast charging", "5G", "Realme", "AMOLED"], "Realme", 19999),

            ("Vivo V29 5G",
             "Aura Light portrait camera, Snapdragon 778G, elegant slim design for photography enthusiasts.",
             {"Display": "6.78-inch AMOLED 120Hz", "Processor": "Snapdragon 778G", "RAM": "8GB", "Storage": "256GB", "Camera": "50MP Aura Light", "Battery": "4600 mAh"},
             ["portrait", "Aura Light", "slim", "5G", "photography"], "Vivo", 33999),
        ],
        "Headphones": [
            ("Sony WH-1000XM5",
             "Industry-leading noise cancellation, 30-hour battery, multipoint Bluetooth. The definitive ANC headphone.",
             {"Type": "Over-ear", "Noise Cancellation": "Yes", "Battery": "30 hr", "Bluetooth": "5.2", "Driver": "30mm"},
             ["ANC", "premium", "wireless", "work from home", "audiophile"], "Sony", 26990),

            ("Sony WH-1000XM4",
             "Legendary ANC with LDAC hi-res audio, 30-hour battery, foldable design. Still one of the best.",
             {"Type": "Over-ear", "Noise Cancellation": "Yes", "Battery": "30 hr", "LDAC": "Yes", "Bluetooth": "5.0"},
             ["ANC", "LDAC", "hi-res", "wireless", "foldable"], "Sony", 19990),

            ("Bose QuietComfort 45",
             "Balanced, natural sound, Bose signature ANC, 24-hour battery. Premium comfort for all-day wear.",
             {"Type": "Over-ear", "Noise Cancellation": "Yes", "Battery": "24 hr", "Bluetooth": "5.1", "Weight": "240g"},
             ["ANC", "Bose", "balanced", "comfortable", "premium"], "Bose", 24990),

            ("JBL Tune 760NC",
             "Active noise cancellation at an affordable price. 35-hour battery, foldable and lightweight.",
             {"Type": "Over-ear", "Noise Cancellation": "Active", "Battery": "35 hr", "Bluetooth": "5.0", "Weight": "218g"},
             ["ANC", "wireless", "JBL", "affordable", "foldable"], "JBL", 7999),

            ("Boat Rockerz 450 Pro",
             "40-hour playtime, Boat signature bass-heavy sound, foldable design. India's most popular budget wireless headphone.",
             {"Type": "Over-ear", "Battery": "40 hr", "Bluetooth": "5.0", "Driver": "40mm"},
             ["budget", "bass", "wireless", "India", "long battery"], "Boat", 1999),

            ("Sennheiser HD 599",
             "Open-back over-ear headphone for home listening. Natural soundstage and detailed German-engineered audio.",
             {"Type": "Over-ear open-back", "Impedance": "50 Ohm", "Driver": "38mm", "Use": "Home/Studio"},
             ["open-back", "audiophile", "natural sound", "studio", "home listening"], "Sennheiser", 11990),
        ],
        "Tablet": [
            ("Apple iPad 10th Gen 64GB Wi-Fi",
             "A14 Bionic chip, 10.9-inch Liquid Retina display, USB-C. The best tablet for students and casual users.",
             {"Display": "10.9-inch Liquid Retina", "Chip": "A14 Bionic", "Storage": "64GB", "Connectivity": "Wi-Fi", "Battery": "28 hr"},
             ["iPad", "iOS", "education", "creative", "USB-C"], "Apple", 44900),

            ("Samsung Galaxy Tab S9 FE 5G",
             "10.9-inch display with S Pen included, 5G connectivity, IP68 water resistance. Work and play anywhere.",
             {"Display": "10.9-inch TFT", "Processor": "Exynos 1380", "RAM": "6GB", "Storage": "128GB", "S Pen": "Included", "5G": "Yes"},
             ["S Pen", "5G", "Samsung", "IP68", "productivity"], "Samsung", 44999),
        ],
        "Smartwatch": [
            ("Apple Watch Series 9 GPS 45mm",
             "S9 chip, Double Tap gesture, Always-On Retina display, ECG and blood oxygen monitoring. Best smartwatch.",
             {"Display": "45mm Always-On Retina", "Chip": "S9", "Health": "ECG, Blood Oxygen, Temperature", "Battery": "18 hr", "GPS": "Yes"},
             ["health", "ECG", "Apple Watch", "fitness", "GPS"], "Apple", 41900),

            ("Samsung Galaxy Watch 6 Classic 47mm",
             "Rotating physical bezel, comprehensive health suite, Wear OS. The Android user's best smartwatch.",
             {"Display": "1.47-inch Super AMOLED", "Health": "BIA, ECG, Blood Oxygen", "Battery": "40 hr", "Rotating Bezel": "Yes"},
             ["Android", "health", "rotating bezel", "Wear OS", "Samsung"], "Samsung", 34999),

            ("Noise ColorFit Ultra 3",
             "1.96-inch AMOLED, Bluetooth calling, 100+ sports modes, SpO2 and stress monitor. Best value smartwatch in India.",
             {"Display": "1.96-inch AMOLED", "Battery": "7 days", "Calling": "Bluetooth", "Sports Modes": "100+", "SpO2": "Yes"},
             ["budget", "calling", "AMOLED", "sports", "India"], "Noise", 3999),
        ],
    },
    "Clothing": {
        "Men's T-Shirts": [
            ("Nike Dri-FIT Training T-Shirt",
             "Sweat-wicking Dri-FIT technology keeps you dry and comfortable during the most intense workouts.",
             {"Material": "100% Polyester", "Fit": "Regular", "Neck": "Round"},
             ["gym", "sport", "dri-fit", "moisture-wicking", "training"], "Nike", 1299),

            ("Adidas Essentials 3-Stripes Tee",
             "Classic Adidas 3-stripes design in a comfortable cotton-polyester blend for everyday casual wear.",
             {"Material": "70% Cotton 30% Recycled Polyester", "Fit": "Regular", "Neck": "Round"},
             ["casual", "classic", "cotton", "everyday", "Adidas"], "Adidas", 999),

            ("Levi's Graphic Crew Neck T-Shirt",
             "Premium cotton, iconic Levi's batwing logo, relaxed fit. A timeless staple for your wardrobe.",
             {"Material": "100% Cotton", "Fit": "Relaxed", "Neck": "Crew"},
             ["cotton", "casual", "premium", "graphic", "logo"], "Levi's", 1499),

            ("Puma Training Essential Tee",
             "Slim fit with DryCELL moisture-wicking technology. Ideal for gym sessions and outdoor sports.",
             {"Material": "100% Polyester", "Fit": "Slim", "Technology": "DryCELL"},
             ["gym", "slim fit", "sport", "Puma", "moisture-wicking"], "Puma", 799),
        ],
        "Men's Jeans": [
            ("Levi's 511 Slim Fit Jeans",
             "Slim through thigh and leg, sits just below the waist. Levi's iconic stretch denim for all-day comfort.",
             {"Fit": "Slim", "Rise": "Below Waist", "Fabric": "99% Cotton 1% Elastane"},
             ["slim", "denim", "casual", "stretch", "Levi's"], "Levi's", 2799),

            ("Wrangler Regular Fit Jeans",
             "Classic 5-pocket regular fit jeans in durable 100% cotton denim. A reliable wardrobe staple.",
             {"Fit": "Regular", "Fabric": "100% Cotton", "Rise": "Mid"},
             ["regular fit", "classic", "cotton", "denim", "casual"], "Wrangler", 1799),

            ("Pepe Jeans Skinny Fit",
             "Super-skinny stretch denim, ankle-length cut. Trendy and comfortable for modern urban style.",
             {"Fit": "Skinny", "Fabric": "96% Cotton 4% Elastane", "Length": "Ankle"},
             ["skinny", "stretch", "trendy", "ankle", "casual"], "Pepe Jeans", 2299),
        ],
        "Women's Dresses": [
            ("Zara Floral Midi Dress",
             "Elegant floral print, V-neck midi length. Perfect for parties, dates, and special occasions.",
             {"Material": "Viscose", "Length": "Midi", "Neck": "V-neck", "Pattern": "Floral"},
             ["floral", "midi", "party", "elegant", "summer"], "Zara", 2499),

            ("H&M Wrap Dress",
             "Tie-front wrap design in flowing fabric. Universally flattering and versatile for office or casual.",
             {"Material": "Woven Fabric", "Length": "Midi", "Closure": "Tie-front"},
             ["wrap", "casual", "versatile", "summer", "office"], "H&M", 1499),

            ("ONLY Bodycon Mini Dress",
             "Stretch-fabric, figure-hugging bodycon silhouette. Great for nights out and social events.",
             {"Material": "95% Polyester 5% Elastane", "Length": "Mini", "Fit": "Bodycon"},
             ["bodycon", "party", "mini", "stretch", "night out"], "ONLY", 1799),

            ("AND Printed Shift Dress",
             "Lightweight knee-length shift dress with a printed pattern. Comfortable for office and casual wear.",
             {"Material": "Polyester", "Length": "Knee", "Fit": "Shift", "Pattern": "Print"},
             ["office", "casual", "shift", "printed", "knee length"], "AND", 1999),
        ],
        "Sports Shoes": [
            ("Nike Air Max 270",
             "Large visible Air Max unit in the heel, breathable mesh upper. A stylish sneaker for running and everyday wear.",
             {"Sole": "Air Max", "Upper": "Mesh + Synthetic", "Closure": "Lace-up", "Activity": "Running/Casual"},
             ["Air Max", "cushion", "stylish", "running", "casual"], "Nike", 9995),

            ("Adidas Ultraboost 22",
             "BOOST midsole returns energy with every stride. Primeknit+ upper for a sock-like fit. The world's best running shoe.",
             {"Sole": "BOOST", "Upper": "Primeknit+", "Activity": "Running", "Drop": "10mm"},
             ["running", "boost", "marathon", "premium", "energy return"], "Adidas", 14999),

            ("Puma RS-X Sneakers",
             "Retro-inspired chunky sole and bold colourways. Make a street-style statement every day.",
             {"Sole": "Rubber", "Upper": "Textile + Leather", "Activity": "Casual", "Style": "Retro"},
             ["casual", "retro", "chunky", "street", "fashion"], "Puma", 4999),

            ("Skechers Go Walk 6",
             "Lightweight slip-on walking shoe with Air-Cooled Goga Mat insole. Comfort for all-day wear.",
             {"Sole": "Goga Mat", "Upper": "Mesh", "Closure": "Slip-on", "Activity": "Walking"},
             ["walking", "comfortable", "slip-on", "lightweight", "daily"], "Skechers", 3299),
        ],
        "Women's Kurtas": [
            ("Biba Printed A-Line Kurta",
             "Cotton-blend A-line kurta with traditional print. Comfortable and elegant for daily ethnic wear.",
             {"Material": "Cotton Blend", "Fit": "A-Line", "Sleeve": "3/4"},
             ["ethnic", "daily wear", "cotton", "A-line", "Indian"], "Biba", 1299),

            ("W Solid Straight Kurta",
             "Solid-colour straight-cut kurta in soft polyester crepe. Great for office and semi-formal occasions.",
             {"Material": "Polyester Crepe", "Fit": "Straight", "Sleeve": "Full"},
             ["office", "solid", "straight", "ethnic", "formal"], "W", 1599),
        ],
    },
    "Home & Kitchen": {
        "Pressure Cooker": [
            ("Prestige Popular Aluminium 5L",
             "Aluminium body, gasket-release system, ISI marked. India's most trusted pressure cooker for over 60 years.",
             {"Capacity": "5 Litres", "Material": "Aluminium", "Safety": "Gasket Release", "ISI": "Yes"},
             ["aluminium", "ISI", "cooking", "kitchen", "India"], "Prestige", 1299),

            ("Hawkins Contura Hard Anodised 3L",
             "Hard-anodised body, contura shape for easy grip, includes separator plate. The healthier pressure cooker.",
             {"Capacity": "3 Litres", "Material": "Hard Anodised", "Includes": "Separator"},
             ["hard anodised", "healthy", "non-toxic", "kitchen", "small family"], "Hawkins", 2199),

            ("Pigeon Favourite Induction 5L",
             "Induction and gas compatible, inner lid, stainless steel body. Great for modern kitchens.",
             {"Capacity": "5 Litres", "Compatible": "Gas + Induction", "Lid": "Inner", "Material": "Stainless Steel"},
             ["induction", "stainless steel", "family", "cooking", "kitchen"], "Pigeon", 999),
        ],
        "Air Fryer": [
            ("Philips Essential Air Fryer 4.1L",
             "Rapid Air Technology uses hot air circulation — up to 90% less fat than deep frying. 13 preset functions.",
             {"Capacity": "4.1 Litres", "Power": "1400W", "Temperature": "80-200°C", "Timer": "60 min", "Functions": "13"},
             ["low fat", "healthy", "rapid air", "Philips", "1400W"], "Philips", 7999),

            ("Wonderchef Prato 6L Digital",
             "6-litre large capacity for families, digital touchscreen with 8 preset menus. Healthy cooking made easy.",
             {"Capacity": "6 Litres", "Power": "1500W", "Control": "Digital Touch", "Presets": "8"},
             ["digital", "large", "family", "healthy cooking", "touchscreen"], "Wonderchef", 4499),

            ("Inalsa Nutri Fry 4L",
             "1400W, cool-touch handle, dishwasher-safe basket. Compact and reliable for small families.",
             {"Capacity": "4 Litres", "Power": "1400W", "Handle": "Cool-touch", "Dishwasher Safe": "Yes"},
             ["compact", "budget", "healthy", "kitchen", "1400W"], "Inalsa", 3499),
        ],
        "Mixer Grinder": [
            ("Preethi Blue Leaf Platinum 750W",
             "750W motor, 4 jars including chutney jar, 3-speed control with pulse. India's most reliable mixer grinder.",
             {"Power": "750W", "Jars": "4", "Speed": "3 + Pulse", "Warranty": "5 Years Motor"},
             ["mixer", "750W", "4 jars", "kitchen", "cooking"], "Preethi", 3499),

            ("Bajaj Rex 500W",
             "500W motor, 3 jars, ergonomic design, reliable for daily Indian cooking needs.",
             {"Power": "500W", "Jars": "3", "Speed": "3", "Warranty": "2 Years"},
             ["mixer", "budget", "500W", "3 jars", "daily use"], "Bajaj", 2199),
        ],
        "Water Purifier": [
            ("Kent Grand Plus 9L RO+UV+TDS",
             "9-litre storage, RO+UV+UF+TDS purification, zero-wastage technology. India's top RO purifier.",
             {"Capacity": "9 Litres", "Purification": "RO+UV+UF+TDS", "Zero Wastage": "Yes", "Warranty": "1 Year + 4 Year Free Service"},
             ["RO", "UV", "drinking water", "health", "Kent"], "Kent", 17999),

            ("Aquaguard Aura RO+UV+MTDS 7L",
             "UV e-boiling technology, smart LED indicator. Delivers safe and pure water from all water sources.",
             {"Capacity": "7 Litres", "Purification": "RO+UV+MTDS", "Indicator": "Smart LED"},
             ["UV", "RO", "safe water", "Aquaguard", "health"], "Aquaguard", 15499),
        ],
    },
    "Sports & Fitness": {
        "Dumbbells": [
            ("Kore PVC Hex Dumbbells 5kg Pair",
             "Vinyl-coated hex design prevents rolling, anti-rust cast iron core. Ideal for beginners building a home gym.",
             {"Weight": "5 kg each", "Material": "PVC coated cast iron", "Shape": "Hex", "Sold as": "Pair"},
             ["home gym", "beginners", "strength", "pair", "fixed weight"], "Kore", 699),

            ("Kore PVC Hex Dumbbells 10kg Pair",
             "10kg pair, hex PVC coating for durability and grip. Great for intermediate home strength training.",
             {"Weight": "10 kg each", "Material": "PVC coated cast iron", "Shape": "Hex", "Sold as": "Pair"},
             ["home gym", "strength", "intermediate", "pair", "fixed weight"], "Kore", 1199),

            ("Powermax Adjustable Dumbbell 5-25kg",
             "One dumbbell replaces 9 pairs (5-25kg in 2.5kg steps). Quick-dial adjustment, massive space-saver.",
             {"Weight Range": "5-25 kg", "Steps": "2.5 kg", "Replaces": "9 pairs", "Material": "Steel + ABS"},
             ["adjustable", "space saving", "home gym", "advanced", "quick dial"], "Powermax", 7999),
        ],
        "Yoga Mat": [
            ("Boldfit TPE Yoga Mat 6mm",
             "Eco-friendly TPE material, non-slip surface both sides, carry strap included. Best beginner yoga mat.",
             {"Thickness": "6mm", "Material": "TPE", "Size": "183 x 61 cm", "Non-slip": "Yes", "Includes": "Carry Strap"},
             ["yoga", "eco-friendly", "TPE", "non-slip", "beginners"], "Boldfit", 799),

            ("Decathlon Corength Mat 8mm",
             "Extra-thick 8mm NBR foam for joint protection. Dotted texture surface for better grip during floor exercises.",
             {"Thickness": "8mm", "Material": "NBR", "Size": "185 x 61 cm", "Texture": "Dotted"},
             ["yoga", "thick", "comfortable", "floor exercise", "beginner"], "Decathlon", 999),
        ],
        "Resistance Bands": [
            ("Boldfit Resistance Bands Set 5-Level",
             "Set of 5 latex bands from 5-40 lbs resistance. Perfect for home workouts and rehabilitation exercises.",
             {"Levels": "5", "Material": "Natural Latex", "Resistance": "5-40 lbs", "Includes": "Carry Bag"},
             ["home workout", "rehabilitation", "latex", "portable", "stretching"], "Boldfit", 599),

            ("Fitlastics Pull-Up Assist Band",
             "Heavy-duty 41-inch loop band for pull-up assistance, mobility work, and resistance training.",
             {"Type": "Loop Band", "Material": "Natural Latex", "Length": "41 inch", "Use": "Pull-up assist, mobility"},
             ["pull-up", "assist", "strength", "mobility", "gym"], "Fitlastics", 799),
        ],
        "Protein Powder": [
            ("MuscleBlaze Whey Protein 1kg Chocolate",
             "24g protein per serving, 5.5g BCAA, lab-tested and certified. India's number one sports nutrition brand.",
             {"Protein per serving": "24g", "BCAA": "5.5g", "Servings": "30", "Flavour": "Chocolate", "Lab Tested": "Yes"},
             ["whey", "protein", "gym", "muscle", "chocolate"], "MuscleBlaze", 1999),

            ("Optimum Nutrition Gold Standard Whey 907g",
             "24g protein, 5.5g BCAA, 4g glutamine per serving. The world's best-selling whey protein supplement.",
             {"Protein per serving": "24g", "BCAA": "5.5g", "Glutamine": "4g", "Servings": "29", "Flavour": "Double Rich Chocolate"},
             ["whey", "premium", "gym", "BCAA", "world's best"], "Optimum Nutrition", 3499),
        ],
    },
    "Books": {
        "Self-Help": [
            ("Atomic Habits by James Clear",
             "Tiny changes, remarkable results. A proven framework to build good habits and break bad ones. Must-read.",
             {"Pages": "319", "Language": "English", "Format": "Paperback", "Publisher": "Random House"},
             ["habits", "productivity", "bestseller", "self-improvement", "motivation"], "Random House", 499),

            ("Rich Dad Poor Dad by Robert Kiyosaki",
             "Classic financial literacy book. Teaches you to make money work for you, not the other way around.",
             {"Pages": "336", "Language": "English", "Format": "Paperback"},
             ["finance", "investment", "money", "wealth", "classic"], "Plata Publishing", 399),

            ("The Psychology of Money by Morgan Housel",
             "Timeless lessons on wealth, greed, and happiness — how people think about and behave with money.",
             {"Pages": "256", "Language": "English", "Format": "Paperback"},
             ["finance", "psychology", "money", "investing", "easy read"], "Harriman House", 449),

            ("Deep Work by Cal Newport",
             "Rules for focused success in a distracted world. Master the skill of deep work to produce at your peak.",
             {"Pages": "296", "Language": "English", "Format": "Paperback"},
             ["productivity", "focus", "deep work", "career", "success"], "Grand Central Publishing", 399),
        ],
        "Fiction": [
            ("The Alchemist by Paulo Coelho",
             "A magical story about following your dreams and listening to your heart. Over 65 million copies sold worldwide.",
             {"Pages": "208", "Language": "English", "Format": "Paperback"},
             ["fiction", "inspirational", "classic", "adventure", "bestseller"], "HarperCollins", 250),

            ("Ikigai by Hector Garcia and Francesc Miralles",
             "The Japanese secret to a long and happy life — finding your reason for being and living it every day.",
             {"Pages": "208", "Language": "English", "Format": "Paperback"},
             ["Japanese", "life purpose", "happiness", "philosophy", "easy read"], "Penguin", 299),
        ],
    },
    "Beauty": {
        "Moisturizer": [
            ("Neutrogena Oil-Free Daily Moisturizer SPF15",
             "Lightweight, non-greasy moisturizer with SPF 15 sun protection. Dermatologist-recommended for oily skin.",
             {"SPF": "15", "Skin Type": "Oily/Combination", "Size": "110ml", "Key Ingredient": "Helioplex"},
             ["oil-free", "SPF", "lightweight", "daily", "dermatologist"], "Neutrogena", 899),

            ("Lakme Peach Milk Moisturizer SPF24",
             "SPF 24 PA++, peachy fragrance, 24-hour deep hydration. India's favourite face moisturizer.",
             {"SPF": "24 PA++", "Size": "120ml", "Duration": "24 hours", "Fragrance": "Peach"},
             ["SPF", "affordable", "daily", "Lakme", "India"], "Lakme", 299),

            ("Himalaya Nourishing Skin Cream 200ml",
             "Aloe vera and winter cherry natural herbs, non-greasy formula, suitable for all skin types.",
             {"Size": "200ml", "Key Ingredients": "Aloe Vera, Winter Cherry", "Skin Type": "All"},
             ["natural", "herbal", "all skin", "Himalaya", "affordable"], "Himalaya", 249),
        ],
        "Sunscreen": [
            ("Minimalist SPF 50 PA++++ Sunscreen 50ml",
             "Lightweight gel formula, broad-spectrum SPF 50, zero white cast. Designed for Indian skin tones.",
             {"SPF": "50 PA++++", "Size": "50ml", "Formula": "Gel", "White Cast": "None"},
             ["SPF 50", "no white cast", "gel", "daily", "Indian skin"], "Minimalist", 329),

            ("Lotus Herbals Safe Sun UV Screen SPF 70",
             "SPF 70 PA+++, matte finish, water-resistant with Ayurvedic herbs. Best for outdoor sun protection.",
             {"SPF": "70 PA+++", "Size": "50g", "Finish": "Matte", "Water Resistant": "Yes"},
             ["SPF 70", "matte", "outdoor", "water resistant", "Lotus"], "Lotus Herbals", 299),
        ],
        "Face Wash": [
            ("Cetaphil Gentle Skin Cleanser 250ml",
             "Soap-free, fragrance-free gentle cleanser. Dermatologist recommended for sensitive, dry, and normal skin.",
             {"Size": "250ml", "Skin Type": "Sensitive/Dry", "Soap-Free": "Yes", "Fragrance-Free": "Yes"},
             ["gentle", "sensitive skin", "soap-free", "daily", "dermatologist"], "Cetaphil", 499),

            ("Himalaya Purifying Neem Face Wash 200ml",
             "Neem and turmeric formula removes excess oil, unclogs pores, prevents pimples. 100% natural.",
             {"Size": "200ml", "Key Ingredients": "Neem, Turmeric", "Skin Type": "Oily/Normal"},
             ["neem", "acne", "oily skin", "natural", "antibacterial"], "Himalaya", 179),
        ],
    },
}


REVIEW_TEMPLATES = {
    5: [
        ("Excellent product!", "Absolutely love it. Exceeded all my expectations. Highly recommended!"),
        ("Best purchase ever", "Top-notch quality, fast delivery. Will buy again for sure."),
        ("Outstanding!",       "Works exactly as described. Very happy with this purchase."),
        ("Worth every rupee",  "Premium quality, great performance. No complaints at all."),
        ("Amazing value",      "Surprised by the quality at this price point. Totally worth it."),
    ],
    4: [
        ("Very good",          "Good product overall. Minor packaging issue but the product itself is great."),
        ("Happy with purchase","Works well. Delivery was prompt. Good value for the price."),
        ("Good quality",       "Satisfied with the product. Matches the description closely."),
        ("Recommended",        "Nice product. Slight improvement in packaging would make it perfect."),
    ],
    3: [
        ("Average product",    "Okay for the price. Nothing exceptional but gets the job done."),
        ("Decent",             "Works as expected. Quality could be a bit better at this price."),
        ("Mixed feelings",     "Has both pros and cons. Functional overall but room for improvement."),
    ],
    2: [
        ("Below expectations", "Expected more based on the description. Somewhat disappointed."),
        ("Not great",          "Quality seems subpar. Would not repurchase at this price."),
    ],
    1: [
        ("Poor quality",       "Very disappointed. Does not match the description at all."),
        ("Waste of money",     "Product quality is terrible. Returning it immediately."),
    ],
}

REVIEWER_NAMES = [
    "Rahul Sharma", "Priya Patel", "Amit Kumar", "Sneha Reddy", "Vijay Nair",
    "Deepa Menon", "Arjun Singh", "Kavya Iyer", "Rohan Gupta", "Anita Desai",
    "Suresh Rao", "Meera Krishnan", "Karthik Raj", "Pooja Verma", "Sanjay Shah",
    "Divya Pillai", "Arun Nambiar", "Rekha Joshi", "Vishal Tiwari", "Shalini Bhat",
    "Neeraj Gupta", "Swati Mishra", "Praveen Kumar", "Lakshmi Narayanan", "Ritika Malik",
]

DISCOUNT_OPTIONS = [0, 0, 0, 5, 5, 10, 10, 15, 20, 25, 30]


def flatten_catalogue():
    rows = []
    for cat, subcats in CATALOGUE.items():
        for subcat, items in subcats.items():
            for name, desc, specs, tags, brand, base_price in items:
                rows.append({
                    "name": name, "description": desc, "category": cat,
                    "subcategory": subcat, "brand": brand,
                    "base_price": float(base_price), "specs": specs, "tags": tags,
                })
    return rows


def seed(reset: bool = False):
    if reset:
        print("Dropping all tables...")
        Base.metadata.drop_all(bind=engine)

    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    db = SessionLocal()

    if not reset and db.query(Product).count() > 0:
        existing = db.query(Product).count()
        print(f"Database already has {existing} products. Use --reset to re-seed.")
        db.close()
        return

    # ── CATEGORIES ────────────────────────────────────────────────────────────
    print("Seeding categories...")
    for cat, subcats in CATALOGUE.items():
        for subcat in subcats:
            if not db.query(Category).filter(Category.name == subcat).first():
                db.add(Category(name=subcat, parent_name=cat))
    db.commit()

    # ── PRODUCTS ──────────────────────────────────────────────────────────────
    all_items = flatten_catalogue()
    print(f"Creating {len(all_items)} products in PostgreSQL...")

    product_objects = []
    for item in all_items:
        p = Product(
            name=item["name"],
            description=item["description"],
            category=item["category"],
            subcategory=item["subcategory"],
            brand=item["brand"],
            price=item["base_price"],
            discount_pct=float(random.choice(DISCOUNT_OPTIONS)),
            inventory_count=random.randint(0, 200),
            specifications=item["specs"],
            tags=item["tags"],
            primary_image=f"https://picsum.photos/seed/{abs(hash(item['name'])) % 9999}/800/600",
            created_at=datetime.utcnow() - timedelta(days=random.randint(1, 365)),
        )
        db.add(p)
        product_objects.append(p)
    db.commit()
    for p in product_objects:
        db.refresh(p)

    # ── IMAGES ────────────────────────────────────────────────────────────────
    print("Adding product images...")
    for p in product_objects:
        seed_base = abs(hash(p.id)) % 9000
        for i in range(random.randint(2, 4)):
            db.add(ProductImage(
                product_id=p.id,
                url=f"https://picsum.photos/seed/{seed_base + i}/800/600",
                alt_text=f"{p.name} — image {i + 1}",
                is_primary=(i == 0),
                sort_order=i,
            ))
    db.commit()

    # ── REVIEWS ───────────────────────────────────────────────────────────────
    print("Adding reviews...")
    for p in product_objects:
        n = random.randint(5, 18)
        ratings = random.choices([5, 5, 5, 4, 4, 4, 3, 3, 2, 1], k=n)
        for rating in ratings:
            title, body = random.choice(REVIEW_TEMPLATES[rating])
            db.add(Review(
                product_id=p.id,
                reviewer_name=random.choice(REVIEWER_NAMES),
                rating=rating,
                title=title,
                body=body,
                verified_purchase=random.random() > 0.3,
                helpful_votes=random.randint(0, 60),
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 300)),
            ))
    db.commit()

    # ── RATING AGGREGATION ────────────────────────────────────────────────────
    print("Computing product ratings...")
    for p in product_objects:
        row = db.execute(
            sql_text("SELECT AVG(rating), COUNT(*) FROM reviews WHERE product_id = :pid"),
            {"pid": p.id},
        ).fetchone()
        p.rating_avg   = round(float(row[0] or 0), 2)
        p.rating_count = int(row[1] or 0)
    db.commit()

    # ── EMBEDDINGS ────────────────────────────────────────────────────────────
    print(f"\nGenerating embeddings with Azure OpenAI text-embedding-3-small...")
    print("(batches of 20 to respect API rate limits)\n")

    from embeddings import embed_batch, build_product_text

    BATCH = 20
    embedded = 0
    for i in range(0, len(product_objects), BATCH):
        batch = product_objects[i: i + BATCH]
        texts = [build_product_text(p) for p in batch]
        try:
            embeddings = embed_batch(texts)
        except Exception as e:
            print(f"  ✗ Batch {i // BATCH + 1} error: {e}")
            continue

        for p, emb in zip(batch, embeddings):
            p.embedding = emb
        db.commit()
        embedded += len(batch)
        print(f"  ✓ Embedded {min(i + BATCH, len(product_objects))}/{len(product_objects)}")
        if i + BATCH < len(product_objects):
            time.sleep(0.5)

    db.close()

    print(f"\n{'=' * 54}")
    print(f"  Seeding complete!")
    print(f"  Products   : {len(product_objects)} unique")
    print(f"  Embedded   : {embedded}")
    print(f"  Vector DB  : pgvector on PostgreSQL")
    print(f"")
    print(f"  Start  : python3 -m uvicorn main:app --reload --port 8001")
    print(f"  Docs   : http://localhost:8001/docs")
    print(f"{'=' * 54}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables before seeding")
    args = parser.parse_args()
    seed(reset=args.reset)
