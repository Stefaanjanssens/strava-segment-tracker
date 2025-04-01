import requests
import os
import sys
import time
import argparse
import json
from dotenv import load_dotenv

# --- Configuration ---
STRAVA_API_BASE_URL = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"

# --- Load Credentials ---
load_dotenv() # Load variables from .env file

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")

# --- Helper Functions ---

def refresh_access_token(client_id, client_secret, refresh_token):
    """Refreshes the Strava Access Token using the Refresh Token."""
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': "refresh_token",
        'f': 'json'
    }
    print("Attempting to refresh access token...")
    try:
        response = requests.post(TOKEN_URL, data=payload, timeout=15)
        response.raise_for_status()
        token_data = response.json()
        new_access_token = token_data.get('access_token')
        expires_at = token_data.get('expires_at')
        if not new_access_token:
            print("Error: Could not retrieve new access token from response.")
            print("Response:", token_data)
            return None
        print(f"Successfully refreshed access token. Expires around: {time.ctime(expires_at) if expires_at else 'N/A'}")
        return new_access_token
    except requests.exceptions.RequestException as e:
        print(f"Error refreshing access token: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status code: {e.response.status_code}")
            print(f"Response content: {e.response.text}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during token refresh: {e}")
        return None

def explore_segments(bounds, access_token, activity_type='riding', min_cat=None, max_cat=None):
    """
    Fetches segments within the specified bounds.

    Args:
        bounds (str): Comma-separated string "sw_lat,sw_lng,ne_lat,ne_lng".
        access_token (str): Valid Strava API access token.
        activity_type (str): 'riding' or 'running'. Defaults to 'riding'.
        min_cat (int, optional): Minimum climb category (0-5).
        max_cat (int, optional): Maximum climb category (0-5).

    Returns:
        list: A list of segment summary objects, or None if an error occurs.
              Returns an empty list if no segments are found.
    """
    explore_url = f"{STRAVA_API_BASE_URL}/segments/explore"
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {
        'bounds': bounds,
        'activity_type': activity_type
    }
    if min_cat is not None:
        params['min_cat'] = min_cat
    if max_cat is not None:
        params['max_cat'] = max_cat

    print(f"Exploring segments within bounds: {bounds} for activity: {activity_type}")
    try:
        response = requests.get(explore_url, headers=headers, params=params, timeout=20) # Increased timeout for explore
        response.raise_for_status() # Raise HTTPError for bad responses

        data = response.json()
        segments = data.get('segments', []) # Segments are nested under 'segments' key
        return segments

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Unauthorized (401). The access token might be invalid or expired.")
        elif e.response.status_code == 429:
            print("Error: Rate Limit Exceeded (429). Please wait before trying again.")
            print("Rate Limit Info:", e.response.headers.get('X-RateLimit-Usage'), e.response.headers.get('X-RateLimit-Limit'))
        elif e.response.status_code == 400:
             print(f"Error: Bad Request (400). Check if the bounds format is correct: 'sw_lat,sw_lng,ne_lat,ne_lng'")
             print(f"Response content: {e.response.text}")
        else:
             print(f"HTTP Error exploring segments: {e}")
             print(f"Response status code: {e.response.status_code}")
             print(f"Response content: {e.response.text}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Network Error exploring segments: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        print(f"Response Text: {response.text if 'response' in locals() else 'N/A'}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during segment exploration: {e}")
        return None

# --- Main Execution ---
if __name__ == "__main__":
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Find Strava segments within a specified geographical area (bounding box).")
    parser.add_argument("sw_lat", type=float, help="Latitude of the South-West corner.")
    parser.add_argument("sw_lng", type=float, help="Longitude of the South-West corner.")
    parser.add_argument("ne_lat", type=float, help="Latitude of the North-East corner.")
    parser.add_argument("ne_lng", type=float, help="Longitude of the North-East corner.")
    parser.add_argument("--activity", choices=['riding', 'running'], default='riding',
                        help="Activity type ('riding' or 'running'). Default: riding.")
    parser.add_argument("--min_cat", type=int, choices=range(6), help="Minimum climb category (0-5).")
    parser.add_argument("--max_cat", type=int, choices=range(6), help="Maximum climb category (0-5).")
    # Could add arguments for min/max grade, etc. if needed

    args = parser.parse_args()

    # Format bounds string required by the API
    bounds_str = f"{args.sw_lat},{args.sw_lng},{args.ne_lat},{args.ne_lng}"
    174.921171, -41.244860, 174.937489, -41.238907

    # --- Validate Credentials ---
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        print("Error: Missing Strava API credentials.")
        print("Please set STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, and STRAVA_REFRESH_TOKEN")
        print("environment variables, for example in a .env file.")
        sys.exit(1)

    # --- Get Access Token ---
    current_access_token = refresh_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)

    if not current_access_token:
        print("Failed to obtain a valid access token. Exiting.")
        sys.exit(1)

    # --- Explore Segments ---
    segments_found = explore_segments(
        bounds_str,
        current_access_token,
        activity_type=args.activity,
        min_cat=args.min_cat,
        max_cat=args.max_cat
    )

    # --- Display Results ---
    if segments_found is None:
        print("An error occurred while fetching segments.")
        sys.exit(1)
    elif not segments_found:
        print("-" * 30)
        print(f"No '{args.activity}' segments found within the specified bounds:")
        print(f"  SW: ({args.sw_lat}, {args.sw_lng})")
        print(f"  NE: ({args.ne_lat}, {args.ne_lng})")
        if args.min_cat is not None or args.max_cat is not None:
             print(f"  Climb Category Filter: min={args.min_cat}, max={args.max_cat}")
        print("-" * 30)
    else:
        print("-" * 50)
        print(f"Found {len(segments_found)} '{args.activity}' segments within bounds:")
        print(f"  SW: ({args.sw_lat}, {args.sw_lng})")
        print(f"  NE: ({args.ne_lat}, {args.ne_lng})")
        if args.min_cat is not None or args.max_cat is not None:
             print(f"  Climb Category Filter: min={args.min_cat}, max={args.max_cat}")
        print("-" * 50)
        print(f"{'ID':<12} {'Name':<50} {'Climb Cat':<10} {'Distance (m)':<15} {'Avg Grade (%)':<15}")
        print("-" * 110)
        for segment in segments_found:
            # The explore endpoint returns a summary, fields might differ slightly from getSegmentById
            seg_id = segment.get('id', 'N/A')
            name = segment.get('name', 'N/A')
            climb_cat = segment.get('climb_category', -1) # Use -1 or similar for non-climbs
            climb_cat_str = str(climb_cat) if climb_cat >= 0 else "N/A"
            distance = segment.get('distance', 0.0)
            avg_grade = segment.get('avg_grade', 0.0)

            # Limit name length for cleaner printing
            max_name_len = 48
            display_name = (name[:max_name_len] + '..') if len(name) > max_name_len else name

            print(f"{seg_id:<12} {display_name:<50} {climb_cat_str:<10} {distance:<15.1f} {avg_grade:<15.1f}")
        print("-" * 110)