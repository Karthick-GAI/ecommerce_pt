/**
 * Generates a category-relevant image URL for a product.
 *
 * loremflickr.com returns real CC-licensed photos matching the keywords.
 * The `lock` parameter (0-9999) makes the same product always get the same photo.
 *
 * Usage:
 *   productImageUrl(product)           // 400×300 card image
 *   productImageUrl(product, 600, 500) // full detail page size
 */

// subcategory → search keywords (most specific → checked first)
const SUBCAT_KEYWORDS = {
  // Electronics
  'Headphones & Earphones':  'headphones,audio',
  'Headphones':              'headphones,music',
  'Earphones':               'earphones,music',
  'Earbuds':                 'earbuds,wireless',
  'TWS Earbuds':             'earbuds,wireless',
  'Smartphones':             'smartphone,mobile',
  'Mobile Phones':           'smartphone,mobile',
  'Laptops':                 'laptop,computer',
  'Ultrabooks':              'laptop,computer',
  'Tablets':                 'tablet,device',
  'Cameras':                 'camera,photography',
  'DSLR Cameras':            'camera,photography',
  'Mirrorless Cameras':      'camera,photography',
  'Smart TV':                'television,smart',
  'Television':              'television,screen',
  'Smart Watches':           'smartwatch,wrist',
  'Wearables':               'smartwatch,wrist',
  'Speakers':                'speaker,audio',
  'Printers':                'printer,office',
  'Monitors':                'monitor,screen',
  'Computer Accessories':    'computer,accessories',

  // Clothing
  "Men's T-Shirts":          'tshirt,men,fashion',
  "Men's Shirts":            'shirt,men,fashion',
  "Men's Jeans":             'jeans,denim',
  "Men's Trousers":          'trousers,men',
  "Men's Ethnic":            'kurta,ethnic,india',
  "Women's Dresses":         'dress,women,fashion',
  "Women's Tops":            'top,women,fashion',
  "Women's Sarees":          'saree,ethnic,india',
  "Women's Kurtas":          'kurta,women,india',
  "Women's Jeans":           'jeans,women,fashion',
  'Sneakers':                'sneakers,shoes',
  'Running Shoes':           'running,shoes',
  'Casual Shoes':            'shoes,casual',
  'Formal Shoes':            'shoes,formal',
  'Sandals':                 'sandals,footwear',
  'Heels':                   'heels,women',
  'Sports Shoes':            'sports,shoes',

  // Books
  'Fiction':                 'books,novel,reading',
  'Non-Fiction':             'books,knowledge',
  'Self-Help':               'books,motivation',
  'Business':                'books,business',
  'Children':                'books,children',
  'Comics':                  'comics,graphic',

  // Sports & Fitness
  'Cricket':                 'cricket,sport',
  'Football':                'football,soccer',
  'Badminton':               'badminton,sport',
  'Tennis':                  'tennis,sport',
  'Yoga':                    'yoga,fitness',
  'Gym Equipment':           'gym,fitness,weights',
  'Cycling':                 'cycling,bicycle',
  'Swimming':                'swimming,pool',
  'Running':                 'running,sport',
  'Trekking':                'trekking,hiking',

  // Furniture
  'Sofa':                    'sofa,furniture,interior',
  'Dining Table':            'dining,furniture',
  'Wardrobe':                'wardrobe,bedroom',
  'Bed':                     'bed,bedroom,furniture',
  'Office Chair':            'chair,office',
  'Bookshelf':               'bookshelf,interior',
  'Study Table':             'desk,study',

  // Home & Kitchen
  'Kitchen Appliances':      'kitchen,appliance',
  'Cookware':                'cookware,kitchen',
  'Dinnerware':              'dishes,kitchen',
  'Storage':                 'storage,home',
  'Bedding':                 'bedding,home',
  'Curtains':                'curtains,interior',
  'Cleaning':                'cleaning,home',
  'Lighting':                'lamp,lighting,interior',

  // Beauty
  'Skincare':                'skincare,beauty',
  'Moisturiser':             'skincare,moisturiser',
  'Sunscreen':               'skincare,sunscreen',
  'Makeup':                  'makeup,cosmetics',
  'Lipstick':                'lipstick,makeup',
  'Foundation':              'foundation,makeup',
  'Haircare':                'haircare,hair',
  'Shampoo':                 'shampoo,hair',
  'Perfume':                 'perfume,fragrance',
  'Men Grooming':            'grooming,men',

  // Automotive
  'Engine Oil':              'car,engine',
  'Car Accessories':         'car,accessories',
  'Tyres':                   'tyre,car',
  'Car Care':                'car,cleaning',
  'Helmets':                 'helmet,motorcycle',
  'Bike Accessories':        'motorcycle,accessories',

  // Toys & Games
  'Action Figures':          'toy,figurine,children',
  'Board Games':             'boardgame,family',
  'Building Blocks':         'lego,blocks,children',
  'Remote Control':          'remote,car,toy',
  'Educational Toys':        'educational,children',
  'Outdoor Toys':            'outdoor,play,children',

  // Grocery
  'Biscuits':                'biscuit,snack,food',
  'Chocolates':              'chocolate,sweets',
  'Beverages':               'beverage,drink',
  'Instant Food':            'instant,food',
  'Dry Fruits':              'dry,fruit,food',
  'Oil & Ghee':              'oil,cooking',
  'Rice & Grains':           'rice,grain,food',
  'Spices':                  'spices,cooking',

  // Baby Products
  'Diapers':                 'baby,infant',
  'Baby Food':               'baby,food',
  'Baby Clothing':           'baby,clothing',
  'Baby Toys':               'baby,toy',
  'Baby Care':               'baby,care',

  // Pet Supplies
  'Dog Food':                'dog,pet',
  'Cat Food':                'cat,pet',
  'Dog Accessories':         'dog,accessories',
  'Cat Accessories':         'cat,accessories',
  'Pet Grooming':            'pet,grooming',

  // Stationery
  'Notebooks':               'notebook,stationery',
  'Pens':                    'pen,writing',
  'Art Supplies':            'art,painting',
  'Office Supplies':         'office,supplies',
}

// category → fallback keywords when subcategory is not in the map
const CAT_KEYWORDS = {
  'Electronics':          'electronics,technology',
  'Clothing':             'fashion,clothing',
  'Books':                'books,reading',
  'Sports & Fitness':     'sports,fitness',
  'Furniture':            'furniture,interior',
  'Home & Living':        'home,decor',
  'Home & Kitchen':       'kitchen,home',
  'Beauty':               'beauty,cosmetics',
  'Automotive':           'automobile,car',
  'Toys':                 'toy,children',
  'Toys & Games':         'toys,games',
  'Grocery':              'food,market',
  'Baby Products':        'baby,care',
  'Pet Supplies':         'pet,animal',
  'Stationery':           'stationery,office',
  'Appliances':           'appliance,home',
}

/** djb2 string hash → stable integer in [0, 9999] */
function hashToLock(str) {
  let h = 5381
  for (let i = 0; i < (str || '').length; i++) {
    h = ((h << 5) + h) ^ str.charCodeAt(i)
    h = h >>> 0  // keep as unsigned 32-bit
  }
  return h % 10000
}

/**
 * Returns a loremflickr URL for a product.
 * @param {object} product - must have at least one of: category, subcategory, name, brand
 * @param {number} w - image width (default 400)
 * @param {number} h - image height (default 300)
 */
export function productImageUrl(product, w = 400, h = 300) {
  const id       = product.id || product.product_id || product.name || 'product'
  const subcat   = product.subcategory || ''
  const category = product.category || ''

  // Pick the most specific keywords available
  const keywords =
    SUBCAT_KEYWORDS[subcat] ||
    CAT_KEYWORDS[category]  ||
    'product,shopping'

  const lock = hashToLock(id)
  return `/imgproxy/${w}/${h}/${keywords}?lock=${lock}`
}
