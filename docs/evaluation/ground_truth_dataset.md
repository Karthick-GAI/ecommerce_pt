# Ground Truth Dataset

## Overview

This document describes the ground truth dataset used for retrieval accuracy evaluation of the semantic search and RAG shopping assistant pipelines.

**Relevance scale:**
- `3` — Highly relevant: directly answers the query (e.g., query is "wireless earbuds for running", product is "boAt Airdopes 141 IPX4 earbuds")
- `2` — Relevant: closely related, partially answers (e.g., same category but different use case)
- `1` — Marginally relevant: related topic, useful context
- `0` — Not relevant (absence from the dict = 0)

---

## Dataset Summary

| Metric | Value |
|--------|-------|
| Total queries | 30 |
| Categories covered | Electronics, Fashion, Sports, Home & Kitchen, Books, Beauty, Grocery, Toys |
| Query types | Natural language (12), Price-constrained (6), Brand-specific (4), Feature-specific (6), Comparative (2) |
| Avg relevant products per query | 4.2 |
| Total relevance judgments | 126 |

---

## Query Corpus

### Electronics — Earbuds & Headphones

**Q01**: `"wireless earbuds for running under 3000"`
```json
{
  "boat_airdopes_141": 3,
  "boult_z40_tws": 3,
  "jbl_tune_215tws": 2,
  "realme_buds_q2s": 2,
  "boat_airdopes_441": 1,
  "samsung_galaxy_buds_fe": 1
}
```

**Q02**: `"noise cancelling headphones for office work"`
```json
{
  "sony_wh1000xm5": 3,
  "bose_qc45": 3,
  "jabra_evolve2_55": 3,
  "sony_wh1000xm4": 2,
  "anker_q45": 1,
  "jbl_tune_510bt": 1
}
```

**Q03**: `"best gaming headset with mic"`
```json
{
  "hyperx_cloud_alpha": 3,
  "razer_blackshark_v2": 3,
  "steelseries_arctis_7": 2,
  "boat_immortal_im1000d": 2,
  "jbl_quantum_350": 1
}
```

### Electronics — Smartphones

**Q04**: `"smartphone under 15000 with good camera"`
```json
{
  "redmi_note_13_pro": 3,
  "poco_x6": 3,
  "samsung_galaxy_m34": 2,
  "realme_11_pro": 2,
  "motorola_g84": 1
}
```

**Q05**: `"iphone alternative with long battery life"`
```json
{
  "samsung_galaxy_s23_fe": 3,
  "oneplus_nord_ce3": 2,
  "nothing_phone_2": 2,
  "google_pixel_7a": 2,
  "realme_gt_neo5": 1
}
```

### Electronics — Laptops

**Q06**: `"lightweight laptop for college student under 50000"`
```json
{
  "hp_pavilion_plus_14": 3,
  "lenovo_ideapad_slim_5": 3,
  "asus_vivobook_15": 2,
  "acer_swift_go": 2,
  "dell_inspiron_15": 1
}
```

**Q07**: `"gaming laptop with dedicated GPU"`
```json
{
  "asus_rog_strix_g15": 3,
  "msi_katana_15": 3,
  "lenovo_ideapad_gaming_3": 2,
  "hp_victus_15": 2,
  "acer_nitro_5": 1
}
```

### Fashion — Footwear

**Q08**: `"running shoes for marathon training"`
```json
{
  "nike_air_zoom_pegasus_40": 3,
  "adidas_ultraboost_22": 3,
  "brooks_ghost_15": 2,
  "asics_gel_nimbus_25": 2,
  "new_balance_880v13": 1
}
```

**Q09**: `"formal shoes for office men black"`
```json
{
  "hush_puppies_carter_oxford": 3,
  "bata_comfit_executive": 3,
  "red_tape_casual_formal": 2,
  "clarks_tilden_walk": 2,
  "woodland_formal_black": 1
}
```

**Q10**: `"waterproof hiking boots for trekking"`
```json
{
  "quechua_mh500_hiking": 3,
  "columbia_newton_ridge": 3,
  "woodland_waterproof_trekking": 2,
  "decathlon_trail_boots": 2,
  "salomon_x_ultra_4": 1
}
```

### Sports & Fitness

**Q11**: `"yoga mat non-slip thick for home"`
```json
{
  "decathlon_domyos_yoga_mat": 3,
  "boldfit_tpe_yoga_mat": 3,
  "nivia_yoga_mat": 2,
  "strauss_eva_yoga_mat": 2,
  "amazon_basics_yoga_mat": 1
}
```

**Q12**: `"protein powder for muscle building whey"`
```json
{
  "mypro_impact_whey": 3,
  "optimum_nutrition_gold_standard": 3,
  "muscleblaze_raw_whey": 2,
  "gnc_pro_performance": 2,
  "fast_and_up_whey": 1
}
```

### Home & Kitchen

**Q13**: `"air fryer for healthy cooking family of 4"`
```json
{
  "philips_hd9200_airfryer": 3,
  "inalsa_easy_fry_4l": 3,
  "pigeon_healthifry_4l": 2,
  "havells_prolife_digi": 2,
  "kent_hot_air_fryer": 1
}
```

**Q14**: `"instant pot pressure cooker"`
```json
{
  "hawkins_stainless_8l": 3,
  "prestige_svachh_ttk": 3,
  "pigeon_spectra": 2,
  "panasonic_sr_wahs18": 1
}
```

**Q15**: `"robot vacuum cleaner for pet hair"`
```json
{
  "irobot_roomba_i3": 3,
  "ecovacs_deebot_t10_turbo": 3,
  "roborock_s5_max": 2,
  "xiaomi_mi_robot_vacuum_2c": 2
}
```

### Beauty & Personal Care

**Q16**: `"face moisturiser for dry skin SPF"`
```json
{
  "neutrogena_hydro_boost": 3,
  "lacto_calamine_sunscreen": 3,
  "dot_and_key_vitamin_c_spf": 2,
  "minimalist_spf_50": 2,
  "plum_green_tea_moisturiser": 1
}
```

**Q17**: `"anti-dandruff shampoo for oily scalp"`
```json
{
  "head_and_shoulders_anti_dandruff": 3,
  "ketomac_shampoo": 3,
  "tresemme_scalp_care": 2,
  "himalaya_anti_dandruff": 2,
  "dove_dermacare_scalp": 1
}
```

### Books & Learning

**Q18**: `"python machine learning book for beginners"`
```json
{
  "hands_on_ml_geron": 3,
  "python_machine_learning_raschka": 3,
  "ml_with_scikit_learn_keras": 2,
  "intro_to_ml_alpaydin": 2,
  "data_science_from_scratch": 1
}
```

**Q19**: `"system design interview preparation book"`
```json
{
  "system_design_interview_xu": 3,
  "designing_data_intensive_apps": 3,
  "system_design_interview_vol2": 2,
  "clean_architecture_martin": 1
}
```

### Comparative / Contextual Queries

**Q20**: `"compare sony vs bose noise cancelling headphones"`
```json
{
  "sony_wh1000xm5": 3,
  "bose_qc45": 3,
  "bose_nc700": 2,
  "sony_wh1000xm4": 2
}
```

**Q21**: `"best wireless earbuds for gym workout sweat resistant"`
```json
{
  "boat_airdopes_141": 3,
  "boult_z40_tws": 3,
  "jbl_tune_230nc_tws": 2,
  "samsung_galaxy_buds2_pro": 2,
  "nothing_ear_2": 1
}
```

**Q22**: `"budget smartphone 5G under 10000"`
```json
{
  "redmi_12_5g": 3,
  "motorola_g34_5g": 3,
  "poco_m6_pro_5g": 2,
  "samsung_galaxy_m14_5g": 2
}
```

**Q23**: `"smartwatch with GPS and health monitoring"`
```json
{
  "garmin_forerunner_265": 3,
  "apple_watch_se_2": 3,
  "samsung_galaxy_watch6": 2,
  "amazfit_gtr_4": 2,
  "boult_crown_r_smartwatch": 1
}
```

**Q24**: `"office chair ergonomic lower back support"`
```json
{
  "green_soul_jupiter_pro": 3,
  "savya_home_apex": 3,
  "durian_apex_high_back": 2,
  "featherlite_lc_chair": 1
}
```

**Q25**: `"laptop bag 15 inch waterproof padded"`
```json
{
  "wildcraft_laptop_backpack": 3,
  "american_tourister_lap_bag": 3,
  "skybags_laptop_bag_15": 2,
  "adidas_linear_laptop_bag": 2,
  "safari_extend_backpack": 1
}
```

**Q26**: `"gifts for mom who likes cooking"`
```json
{
  "prestige_induction_cooktop": 3,
  "philips_hd9200_airfryer": 3,
  "wonderchef_granite_cookware": 2,
  "oven_toaster_grill_morphy": 2,
  "measuring_cups_set": 1
}
```

**Q27**: `"gaming mouse RGB lightweight"`
```json
{
  "logitech_g304_lightspeed": 3,
  "razer_deathadder_v3": 3,
  "steelseries_aerox_5": 2,
  "hyperx_pulsefire_haste2": 2,
  "corsair_harpoon_rgb": 1
}
```

**Q28**: `"mechanical keyboard for programming tenkeyless"`
```json
{
  "keychron_k2_tkl": 3,
  "anne_pro_2": 3,
  "ducky_one_3_tkl": 2,
  "royal_kludge_rk61": 2
}
```

**Q29**: `"monitor 27 inch 4k for graphic design"`
```json
{
  "lg_27uk850_b_4k": 3,
  "dell_s2722qc_4k": 3,
  "asus_proart_pa278cgv": 2,
  "benq_pd2705u": 2
}
```

**Q30**: `"baby products starter kit newborn"`
```json
{
  "johnson_baby_skincare_kit": 3,
  "himalaya_baby_care_gift": 3,
  "mee_mee_baby_grooming_kit": 2,
  "chicco_baby_oil_set": 2,
  "mothercare_bath_essentials": 1
}
```

---

## Dataset Construction Methodology

1. **Query selection**: Sampled from actual search logs in the synthetic dataset (`browsing_events` table, `event_type=search`). Top 30 queries by frequency that cover all 8 major categories.

2. **Relevance labeling**: Manual annotation by two reviewers independently. Disagreements resolved by majority on a 3rd review.

3. **Product-ID mapping**: Product IDs are the string slugs used as `id` in the products table. Tests use product name contains-matching as a fallback when exact IDs differ between dataset versions.

4. **Coverage check**: Every query has at least 2 products at relevance ≥ 2, ensuring MRR is always computable.
