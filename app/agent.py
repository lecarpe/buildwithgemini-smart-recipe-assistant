# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

import dotenv
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

dotenv.load_dotenv()

FIRESTORE_PROJECT = "qwiklabs-gcp-02-026f60d72c39"
BUCKET_NAME = "smart-recipe-assistant-assets-qwiklabs-gcp-02-026f60d72c39"
DEPLOYMENT_METADATA_PATH = Path(__file__).parent.parent / "deployment_metadata.json"


def _get_agent_engine_resource_name() -> str | None:
    if DEPLOYMENT_METADATA_PATH.exists():
        try:
            with open(DEPLOYMENT_METADATA_PATH) as f:
                data = json.load(f)
                return data.get("remote_agent_runtime_id")
        except Exception:
            pass
    return None


agent_engine_resource_name = _get_agent_engine_resource_name()
code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name
)


def _get_firestore_client() -> firestore.Client:
    return firestore.Client(project=FIRESTORE_PROJECT)


def search_recipes(query: str = "") -> str:
    """Search for recipes in the Firestore database by name, ingredient, or cuisine.

    Args:
        query: Optional search keyword (e.g. 'pasta', 'Italian', 'chicken'). If empty, lists all recipes.

    Returns:
        JSON string containing the matching recipes.
    """
    db = _get_firestore_client()
    recipes_ref = db.collection("recipes")
    docs = recipes_ref.stream()

    results = []
    q_lower = query.lower().strip()
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        if not q_lower:
            results.append(data)
        else:
            name_match = q_lower in data.get("name", "").lower()
            cuisine_match = q_lower in data.get("cuisine", "").lower()
            ingredients_match = any(
                q_lower in ing.lower() for ing in data.get("ingredients", [])
            )
            if name_match or cuisine_match or ingredients_match:
                results.append(data)

    return json.dumps(results, indent=2)


def add_recipe(
    name: str,
    cuisine: str,
    prep_time_minutes: int,
    ingredients: list[str],
    instructions: str,
) -> str:
    """Add a new recipe to the Firestore database.

    Args:
        name: Name of the recipe (e.g. 'Garlic Butter Shrimp')
        cuisine: Type of cuisine (e.g. 'Italian', 'Mexican', 'Asian')
        prep_time_minutes: Preparation/cook time in minutes
        ingredients: List of ingredient strings
        instructions: Step-by-step cooking instructions

    Returns:
        Confirmation message with the created recipe ID.
    """
    db = _get_firestore_client()
    recipe_id = name.lower().replace(" ", "_")
    recipe_data = {
        "id": recipe_id,
        "name": name,
        "cuisine": cuisine,
        "prep_time_minutes": prep_time_minutes,
        "ingredients": ingredients,
        "instructions": instructions,
    }
    db.collection("recipes").document(recipe_id).set(recipe_data)
    return f"Successfully added recipe '{name}' with ID '{recipe_id}' to Firestore."


def get_recipe(recipe_id: str) -> str:
    """Get detailed information for a specific recipe from Firestore by ID.

    Args:
        recipe_id: The ID of the recipe (e.g. 'creamy_garlic_pasta').

    Returns:
        JSON string with recipe details or error message if not found.
    """
    db = _get_firestore_client()
    doc = db.collection("recipes").document(recipe_id).get()
    if doc.exists:
        return json.dumps(doc.to_dict(), indent=2)
    return f"Recipe with ID '{recipe_id}' not found in database."


def generate_dish_image(
    dish_name: str,
    description: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Generates an AI visual image of a dish using gemini-3.1-flash-lite-image in the global region.
    Saves the image as an artifact using tool_context and uploads it to the public Cloud Storage bucket.

    Args:
        dish_name: Name of the dish (e.g. 'Creamy Garlic Pasta').
        description: Optional details about plating or key ingredients.

    Returns:
        The public Cloud Storage image URL (https://storage.googleapis.com/<bucket>/<object>).
    """
    prompt = f"A delicious, appetizing, professionally photographed plate of {dish_name}. {description}".strip()
    client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT, location="global")
    res = client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=prompt,
        config=dict(response_modalities=["IMAGE"]),
    )

    image_bytes = None
    mime_type = "image/png"
    for candidate in res.candidates:
        for part in candidate.content.parts:
            if part.inline_data and part.inline_data.data:
                image_bytes = part.inline_data.data
                mime_type = part.inline_data.mime_type or "image/png"
                break

    if not image_bytes:
        return f"Failed to generate image for dish '{dish_name}'."

    ext = "jpg" if "jpeg" in mime_type else "png"
    filename = f"dishes/{dish_name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}.{ext}"

    # 1. Save with tool_context.save_artifact for Playground Artifacts panel
    if tool_context:
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename, artifact_part)

    # 2. Upload image bytes to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT)
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    return f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"


def generate_dish_video(
    dish_name: str,
    description: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Generates a short AI video of a dish using Google's Omni model (gemini-omni-flash-preview) in the global region.
    Saves the video as an artifact using tool_context and uploads it to the public Cloud Storage bucket.

    Args:
        dish_name: Name of the dish or recipe item (e.g. 'Sourdough Pizza', 'Molten Lava Cake').
        description: Optional details about the cooking action or presentation (e.g. 'sizzling in pan', 'cheese pull').

    Returns:
        The public Cloud Storage video URL (https://storage.googleapis.com/<bucket>/<object>).
    """
    prompt = f"A short, high quality, mouth-watering video of {dish_name}. {description}".strip()
    client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT, location="global")

    try:
        interaction = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )
    except Exception as e:
        return f"Error generating video with gemini-omni-flash-preview: {str(e)}"

    video_bytes = None
    if hasattr(interaction, "output_video") and interaction.output_video and interaction.output_video.data:
        raw_data = interaction.output_video.data
        if isinstance(raw_data, str):
            video_bytes = base64.b64decode(raw_data)
        elif isinstance(raw_data, bytes):
            video_bytes = raw_data

    if not video_bytes and hasattr(interaction, "steps"):
        for step in getattr(interaction, "steps", []):
            if getattr(step, "type", None) == "model_output":
                for item in getattr(step, "content", []):
                    if getattr(item, "type", None) == "video" and getattr(item, "data", None):
                        raw_data = item.data
                        if isinstance(raw_data, str):
                            video_bytes = base64.b64decode(raw_data)
                        elif isinstance(raw_data, bytes):
                            video_bytes = raw_data
                        break

    if not video_bytes:
        return f"Failed to generate video for dish '{dish_name}'."

    filename = f"videos/{dish_name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}.mp4"

    # 1. Save with tool_context.save_artifact so it shows up in Playground's Artifacts panel
    if tool_context:
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
        tool_context.save_artifact(filename, artifact_part)

    # 2. Upload video bytes to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT)
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(video_bytes, content_type="video/mp4")

    return f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"


def fetch_online_recipes(query: str = "") -> str:
    """Fetch real-world recipes and culinary ideas from the public TheMealDB API.

    Args:
        query: Optional meal name or ingredient search term (e.g. 'pasta', 'chicken', 'tacos'). If empty, fetches a random meal.

    Returns:
        JSON string containing matching online recipes, ingredients, and preparation instructions.
    """
    if not query.strip():
        url = "https://www.themealdb.com/api/json/v1/1/random.php"
    else:
        encoded_query = urllib.parse.quote(query.strip())
        url = f"https://www.themealdb.com/api/json/v1/1/search.php?s={encoded_query}"

    try:
        req = urllib.request.urlopen(url, timeout=5)
        data = json.loads(req.read().decode("utf-8"))
        meals = data.get("meals") or []

        results = []
        for meal in meals[:3]:
            ingredients = []
            for i in range(1, 21):
                ing = meal.get(f"strIngredient{i}")
                measure = meal.get(f"strMeasure{i}")
                if ing and ing.strip():
                    ingredients.append(f"{measure.strip() if measure else ''} {ing.strip()}".strip())

            results.append({
                "meal": meal.get("strMeal"),
                "category": meal.get("strCategory"),
                "area": meal.get("strArea"),
                "instructions": meal.get("strInstructions"),
                "ingredients": ingredients,
                "thumbnail": meal.get("strMealThumb"),
            })

        if not results:
            return f"No online recipes found on TheMealDB for query: '{query}'."

        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error fetching online recipes from TheMealDB: {str(e)}"


def geocode_address(address: str) -> str:
    """Uses Google Maps Geocoding API to convert an address string into latitude and longitude coordinates.

    Args:
        address: The address or city/location string (e.g., 'Rome, Italy', '1600 Amphitheatre Pkwy, Mountain View, CA').

    Returns:
        JSON string containing formatted address and location coordinates (latitude, longitude).
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    encoded_address = urllib.parse.quote(address)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"

    try:
        req = urllib.request.urlopen(url, timeout=5)
        data = json.loads(req.read().decode("utf-8"))
        results = data.get("results") or []
        if not results:
            return f"No geocoding results found for address: '{address}'."

        first_res = results[0]
        location = first_res.get("geometry", {}).get("location", {})
        formatted_address = first_res.get("formatted_address", address)

        return json.dumps({
            "address": formatted_address,
            "location": {
                "latitude": location.get("lat"),
                "longitude": location.get("lng"),
            }
        }, indent=2)
    except Exception as e:
        return f"Error calling Geocoding API: {str(e)}"


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "restaurant",
    radius_meters: float = 1000.0,
) -> str:
    """Uses Google Places API (New) to search for nearby places of a specific type (e.g. 'restaurant', 'bakery', 'supermarket').

    Args:
        latitude: Latitude coordinate of the central location.
        longitude: Longitude coordinate of the central location.
        place_type: Type of place to search for (e.g. 'restaurant', 'bakery', 'supermarket', 'cafe').
        radius_meters: Radius in meters around the central location (default: 1000.0).

    Returns:
        JSON string containing matching places with key fields (name, address, location).
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    url = "https://places.googleapis.com/v1/places:searchNearby"
    payload = json.dumps({
        "includedTypes": [place_type],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": radius_meters,
            }
        }
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }

    try:
        req = urllib.request.Request(url, data=payload, headers=headers)
        res = urllib.request.urlopen(req, timeout=5)
        data = json.loads(res.read().decode("utf-8"))
        places = data.get("places") or []

        parsed_places = []
        for p in places:
            display_name = p.get("displayName", {}).get("text", "")
            address = p.get("formattedAddress", "")
            loc = p.get("location", {})
            parsed_places.append({
                "name": display_name,
                "address": address,
                "location": {
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                }
            })

        if not parsed_places:
            return f"No nearby places of type '{place_type}' found."

        return json.dumps(parsed_places, indent=2)
    except Exception as e:
        return f"Error calling Places API (New): {str(e)}"


async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Smart Recipe Assistant, a culinary helper that searches, retrieves, and adds "
        "recipes using Firestore, fetches web recipes via TheMealDB API, generates visual dish "
        "photos, finds nearby restaurants/supermarkets using Google Maps and Places APIs, and "
        "executes Python code safely in a sandbox when needed. You remember the user's stated "
        "preferences and dietary restrictions across conversations and use them to personalize your responses."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=code_executor,
    tools=[
        PreloadMemoryTool(),
        search_recipes,
        add_recipe,
        get_recipe,
        generate_dish_image,
        generate_dish_video,
        fetch_online_recipes,
        geocode_address,
        find_nearby_places,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
