from google.cloud import firestore

FIRESTORE_PROJECT = "qwiklabs-gcp-02-026f60d72c39"

def seed_recipes():
    db = firestore.Client(project=FIRESTORE_PROJECT)
    collection_ref = db.collection("recipes")

    recipes = [
        {
            "id": "creamy_garlic_pasta",
            "name": "Creamy Garlic Pasta",
            "cuisine": "Italian",
            "prep_time_minutes": 15,
            "ingredients": ["pasta", "garlic", "heavy cream", "parmesan", "butter", "black pepper"],
            "instructions": "1. Boil pasta according to package instructions. 2. Sauté minced garlic in butter. 3. Stir in heavy cream and grated parmesan. 4. Toss with pasta and black pepper.",
        },
        {
            "id": "classic_avocado_toast",
            "name": "Classic Avocado Toast",
            "cuisine": "American",
            "prep_time_minutes": 5,
            "ingredients": ["bread", "avocado", "lemon juice", "red pepper flakes", "salt"],
            "instructions": "1. Toast bread slices until golden brown. 2. Mash avocado with lemon juice and salt. 3. Spread onto toast and sprinkle red pepper flakes.",
        },
        {
            "id": "spicy_chicken_tacos",
            "name": "Spicy Chicken Tacos",
            "cuisine": "Mexican",
            "prep_time_minutes": 20,
            "ingredients": ["chicken breast", "taco seasoning", "tortillas", "lime", "cilantro", "salsa"],
            "instructions": "1. Season and grill chicken breast. 2. Slice chicken into strips. 3. Warm tortillas and assemble with chicken, salsa, fresh cilantro, and lime squeeze.",
        },
        {
            "id": "veggie_stir_fry",
            "name": "Vegetable Stir Fry",
            "cuisine": "Asian",
            "prep_time_minutes": 12,
            "ingredients": ["broccoli", "bell pepper", "soy sauce", "sesame oil", "garlic", "tofu"],
            "instructions": "1. Sauté cubed tofu until golden. 2. Add chopped broccoli and bell peppers. 3. Stir in minced garlic and soy sauce. 4. Drizzle sesame oil and serve hot.",
        },
    ]

    print(f"Seeding recipes to Firestore project '{FIRESTORE_PROJECT}'...")
    for recipe in recipes:
        doc_ref = collection_ref.document(recipe["id"])
        doc_ref.set(recipe)
        print(f"  - Added recipe: {recipe['name']} (ID: {recipe['id']})")

    print("✅ Seeding complete!")

if __name__ == "__main__":
    seed_recipes()
