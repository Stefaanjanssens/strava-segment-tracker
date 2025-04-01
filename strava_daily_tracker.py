import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import datetime
import sys
import configparser
import time
from io import StringIO # Needed for creating config in cloud environments

# --- Configuration ---
CONFIG_FILE = 'config.ini'
MASTER_CSV_FILE = 'all_segments_log.csv'
PLOT_DIR = 'plots' # Directory to store plots

def load_config():
    """
    Loads configuration from config.ini or environment variables.
    Reads Strava credentials and parses the comma-separated segment IDs.
    Returns a dictionary containing credentials and the list of segment IDs.
    """
    config_data = {}
    use_env_vars = False

    # Check for environment variables first (useful for cloud environments)
    env_client_id = os.environ.get('STRAVA_CLIENT_ID')
    env_client_secret = os.environ.get('STRAVA_CLIENT_SECRET')
    env_refresh_token = os.environ.get('STRAVA_REFRESH_TOKEN')
    env_segment_ids = os.environ.get('STRAVA_SEGMENT_IDS') # Comma-separated string

    if all([env_client_id, env_client_secret, env_refresh_token, env_segment_ids]):
        print("DEBUG: Loading configuration from environment variables.")
        config_data = {
            'client_id': env_client_id,
            'client_secret': env_client_secret,
            'refresh_token': env_refresh_token,
            'segment_ids_str': env_segment_ids
        }
        use_env_vars = True
    elif os.path.exists(CONFIG_FILE):
        print(f"DEBUG: Loading configuration from file: {CONFIG_FILE}")
        config = configparser.ConfigParser()
        try:
            config.read(CONFIG_FILE, encoding='utf-8')
            if 'Strava' not in config:
                print(f"Error: [Strava] section missing in '{CONFIG_FILE}'.")
                sys.exit(1)

            required_keys = ['client_id', 'client_secret', 'refresh_token', 'segment_ids']
            if not all(key in config['Strava'] for key in required_keys):
                missing = [key for key in required_keys if key not in config['Strava']]
                print(f"Error: Missing keys ({', '.join(missing)}) in [Strava] section of '{CONFIG_FILE}'.")
                sys.exit(1)

            config_data = {
                'client_id': config['Strava']['client_id'],
                'client_secret': config['Strava']['client_secret'],
                'refresh_token': config['Strava']['refresh_token'],
                'segment_ids_str': config['Strava']['segment_ids']
            }
        except Exception as e:
            print(f"Error reading configuration file '{CONFIG_FILE}': {e}")
            sys.exit(1)
    else:
        print(f"Error: Configuration not found.")
        print(f"Please create '{CONFIG_FILE}' or set STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET,")
        print("STRAVA_REFRESH_TOKEN, and STRAVA_SEGMENT_IDS environment variables.")
        sys.exit(1)

    # Parse segment IDs
    try:
        segment_ids_raw = config_data['segment_ids_str']
        parsed_segment_ids = [s_id.strip() for s_id in segment_ids_raw.split(',') if s_id.strip()]
        if not parsed_segment_ids:
            raise ValueError("No valid segment IDs found after parsing.")

        config_data['segment_id_list'] = parsed_segment_ids
        print(f"DEBUG: Parsed segment IDs: {parsed_segment_ids}")

    except ValueError as e:
        print(f"Error parsing segment_ids: {e}")
        print("Ensure segment_ids are provided as a non-empty, comma-separated list.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error parsing segment_ids: {e}")
        sys.exit(1)

    # Remove the raw string key before returning
    del config_data['segment_ids_str']
    print(f"DEBUG: Returning config dictionary.")
    return config_data


def refresh_access_token(app_config):
    """Refreshes the Strava access token using the refresh token."""
    print("Refreshing Strava access token...")
    auth_url = "https://www.strava.com/oauth/token"
    payload = {
        'client_id': app_config['client_id'],
        'client_secret': app_config['client_secret'],
        'refresh_token': app_config['refresh_token'],
        'grant_type': "refresh_token",
        'f': 'json'
    }
    try:
        response = requests.post(auth_url, data=payload, timeout=30)
        response.raise_for_status()
        new_tokens = response.json()
        print("Access token refreshed successfully.")
        return new_tokens['access_token']
    except requests.exceptions.RequestException as e:
        response_status = response.status_code if 'response' in locals() and response else 'N/A'
        response_text = response.text if 'response' in locals() and response else 'N/A'
        print(f"Error refreshing Strava token: {e}")
        print(f"Response status: {response_status}")
        print(f"Response text (partial): {response_text[:500]}") # Limit response text length
        print("Critical error: Cannot proceed without a valid access token. Exiting.")
        sys.exit(1)


def get_segment_data(segment_id, access_token):
    """
    Fetches segment ID, name, total effort count, and total athlete count
    from Strava API.
    """
    print(f"Fetching data for segment ID: {segment_id}...")
    api_url = f"https://www.strava.com/api/v3/segments/{segment_id}"
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        # Add a small delay to be polite to the API
        time.sleep(0.5)
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        segment_name = data.get('name', f"Unknown Segment {segment_id}")
        effort_count = data.get('effort_count', 0) # Total attempts
        athlete_count = data.get('athlete_count', 0) # Total unique athletes
        print(f"  Segment {segment_id} ('{segment_name}') data fetched: Total Efforts={effort_count}, Total Athletes={athlete_count}")
        return {
            'id': segment_id,
            'name': segment_name,
            'effort_count': effort_count,
            'athlete_count': athlete_count
        }
    except requests.exceptions.RequestException as e:
        response_status = response.status_code if 'response' in locals() and response else 'N/A'
        response_text = response.text if 'response' in locals() and response else 'N/A'
        print(f"Error fetching data for segment {segment_id}: {e}")
        print(f"  Response status: {response_status}")
        print(f"  Response text (partial): {response_text[:500]}")
        return None # Return None on error for this segment


def update_master_log(segment_data):
    """
    Updates the master CSV log file (all_segments_log.csv) with daily data.
    Calculates attempts since the last run for this segment (daily attempts).
    Sets daily_attempts to 0 for the very first entry of a segment.
    Appends a new data row in the specified format:
    segment_id,segment_name,date,total_attempts_on_date,daily_attempts,athlete_count
    """
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    try:
        segment_id_int = int(segment_data['id'])
    except (ValueError, TypeError):
        print(f"ERROR: Invalid segment ID format received: {segment_data.get('id')}. Skipping update.")
        return

    segment_name = segment_data['name']
    current_total_attempts = int(segment_data.get('effort_count', 0) or 0)
    current_athlete_count = int(segment_data.get('athlete_count', 0) or 0)

    last_total_attempts = 0
    last_date_str = "N/A"
    is_first_entry_for_segment = True # Assume it's the first entry initially
    df = None

    header = "segment_id,segment_name,date,total_attempts_on_date,daily_attempts,athlete_count\n"
    file_exists = os.path.exists(MASTER_CSV_FILE)
    file_is_empty = not file_exists or os.path.getsize(MASTER_CSV_FILE) == 0

    if not file_is_empty:
        print(f"DEBUG: Reading existing log file: {MASTER_CSV_FILE}")
        try:
            df = pd.read_csv(MASTER_CSV_FILE, parse_dates=['date'], dtype={'segment_id': 'Int64'})

            if not df.empty:
                # Filter for the current segment
                segment_df = df[df['segment_id'].notna() & (df['segment_id'] == segment_id_int)].sort_values(by='date')

                if not segment_df.empty:
                    # *** If we find previous entries, it's NOT the first entry ***
                    is_first_entry_for_segment = False
                    print(f"DEBUG: Found previous entries for segment {segment_id_int}.")

                    last_entry = segment_df.iloc[-1]
                    last_date_str = last_entry['date'].strftime('%Y-%m-%d')
                    # print(f"DEBUG: last_entry data: {last_entry.to_dict()}") # Uncomment for deep debugging

                    if 'total_attempts_on_date' in last_entry and pd.notna(last_entry['total_attempts_on_date']):
                        try:
                            last_total_attempts = int(last_entry['total_attempts_on_date'])
                            print(f"DEBUG: Successfully read last_total_attempts: {last_total_attempts} from {last_date_str}")
                        except (ValueError, TypeError):
                            print(f"Warning: Could not convert last 'total_attempts_on_date' ({last_entry['total_attempts_on_date']}) to int for segment {segment_id_int}. Assuming 0 previous.")
                            last_total_attempts = 0
                    else:
                        print(f"Warning: 'total_attempts_on_date' column missing or NaN in last entry for segment {segment_id_int} on {last_date_str}. Assuming 0 previous.")
                        last_total_attempts = 0
                else:
                    # Segment ID not found, so it *is* the first entry for this segment
                    print(f"DEBUG: Segment {segment_id_int} not found in existing data. Marking as first entry.")
                    is_first_entry_for_segment = True
                    last_total_attempts = 0
            else:
                file_is_empty = True
                print(f"DEBUG: Log file '{MASTER_CSV_FILE}' was found but appears empty.")
                is_first_entry_for_segment = True # Treat as first if file was empty
                last_total_attempts = 0

        except pd.errors.EmptyDataError:
             file_is_empty = True
             print(f"DEBUG: Log file '{MASTER_CSV_FILE}' is empty (pandas EmptyDataError).")
             is_first_entry_for_segment = True
             last_total_attempts = 0
        except KeyError as e:
             print(f"Warning: Key error (likely missing column: {e}) reading '{MASTER_CSV_FILE}'. Header might be wrong. Assuming 0 previous attempts.")
             # We might have found the segment ID row but columns are bad.
             # Hard to know if it *was* the first entry. Let's reset attempts but assume not first if ID was findable.
             # Note: The check `if not segment_df.empty` above handles if the ID itself caused the KeyError during filtering.
             # This KeyError handles cases where ID was found, but column access failed later.
             # If segment_df was populated, is_first_entry_for_segment would be False already.
             last_total_attempts = 0
        except Exception as e:
            print(f"Warning: Could not read/parse '{MASTER_CSV_FILE}'. History might be incomplete. Error: {e}")
            file_is_empty = True # Treat as if file needs header/recreation
            is_first_entry_for_segment = True # Assume first if we can't parse history
            last_total_attempts = 0

    else:
        print(f"DEBUG: Master log file '{MASTER_CSV_FILE}' not found or empty. Creating.")
        is_first_entry_for_segment = True # Definitely the first entry if file doesn't exist
        last_total_attempts = 0

    # --- Calculate daily attempts based on whether it's the first entry ---
    if is_first_entry_for_segment:
        daily_attempts = 0
        print(f"DEBUG: Determined this is the first entry for segment {segment_id_int}, setting daily_attempts to 0.")
    else:
        # It's not the first entry, calculate the difference
        daily_attempts = current_total_attempts - last_total_attempts
        print(f"DEBUG: Not first entry. Calculated daily_attempts: {current_total_attempts} - {last_total_attempts} = {daily_attempts}")

        # Handle potential negative values (e.g., Strava recalculation) AFTER the difference is calculated
        if daily_attempts < 0:
            print(f"Warning: Segment {segment_id_int} - Calculated daily attempts negative ({daily_attempts}). Current total ({current_total_attempts}) < last total ({last_total_attempts} on {last_date_str}). Resetting daily attempts to 0.")
            daily_attempts = 0
    # --- End of daily attempts calculation ---

    print(f"  Segment {segment_id_int} ('{segment_name}'):")
    print(f"    Current Total Attempts: {current_total_attempts}")
    print(f"    Last Recorded Total:    {last_total_attempts} (on {last_date_str})")
    print(f"    Attempts Today (Daily): {daily_attempts}") # This reflects the new logic
    print(f"    Total Unique Athletes:  {current_athlete_count}")

    # Prepare the segment name for CSV
    escaped_segment_name = segment_name.replace('"', '""')
    quoted_segment_name = f'"{escaped_segment_name}"'

    # Ensure integer types before creating the row string
    daily_attempts_int = int(daily_attempts) # Ensure type

    # Prepare new data row string
    new_data_row = f"{segment_id_int},{quoted_segment_name},{today_str},{current_total_attempts},{daily_attempts_int},{current_athlete_count}\n"

    # --- File Writing Logic (minor refinement for clarity) ---
    try:
        # Determine write mode ('w' if new/empty, 'a' otherwise)
        write_mode = 'a'
        needs_header = False
        if file_is_empty or not file_exists:
            # If the file doesn't exist OR it exists but we determined it's empty (or couldn't parse)
            write_mode = 'w'
            needs_header = True
            print(f"DEBUG: Setting write mode to 'w', needs_header=True")
        else:
             print(f"DEBUG: Setting write mode to 'a', needs_header=False")

        with open(MASTER_CSV_FILE, write_mode, newline='', encoding='utf-8') as f:
            if needs_header:
                f.write(header)
                print(f"Wrote header to {MASTER_CSV_FILE}")
            f.write(new_data_row)
        print(f"Appended data for segment {segment_id_int} to '{MASTER_CSV_FILE}'")

    except IOError as e:
        print(f"ERROR: Could not write to CSV file '{MASTER_CSV_FILE}': {e}")

def generate_plot(segment_id, segment_name):
    """
    Generates a plot of *daily* attempts for a specific segment
    reading data from the master CSV. Ensures the first point is zero.
    """
    plot_filename = f"segment_{segment_id}_plot.png"
    plot_filepath = os.path.join(PLOT_DIR, plot_filename)
    print(f"Generating plot '{plot_filepath}' for segment {segment_id}...")

    # Create plot directory if it doesn't exist
    os.makedirs(PLOT_DIR, exist_ok=True)

    # Check if master CSV exists before trying to read
    if not os.path.exists(MASTER_CSV_FILE):
         print(f"Plotting skipped: Master CSV file '{MASTER_CSV_FILE}' not found.")
         return

    try:
        # Read master CSV, setting 'date' column as index
        df_all = pd.read_csv(MASTER_CSV_FILE, parse_dates=['date'], index_col='date')

        # Filter for the specific segment ID (convert segment_id to int for matching)
        df_segment = df_all[df_all['segment_id'] == int(segment_id)].copy() # Use .copy() to avoid SettingWithCopyWarning

        # Check if DataFrame is empty or lacks the required 'daily_attempts' column
        if df_segment.empty or 'daily_attempts' not in df_segment.columns:
             print(f"Plotting skipped: No data or 'daily_attempts' column found for segment {segment_id} in '{MASTER_CSV_FILE}'. Check header/data.")
             return
        if len(df_segment) < 1:
             print(f"Plotting skipped: CSV has no data rows for segment {segment_id}.")
             return

        # Ensure data is sorted by date
        df_segment.sort_index(inplace=True)

        # --- Add synthetic zero point for plotting daily attempts ---
        # Create a date point slightly before the first actual data point
        first_real_date = df_segment.index.min()
        zero_point_date = first_real_date - pd.Timedelta(days=1) # One day before
        # Create a DataFrame for the zero point using the 'daily_attempts' column
        zero_point_df = pd.DataFrame({'daily_attempts': [0]}, index=[zero_point_date])
        # Concatenate the zero point at the beginning using the 'daily_attempts' column
        df_to_plot = pd.concat([zero_point_df, df_segment[['daily_attempts']]])
        # --- End synthetic zero point addition ---

        # Proceed with plotting using df_to_plot and the 'daily_attempts' column
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(df_to_plot.index, df_to_plot['daily_attempts'], marker='o', linestyle='-')

        # Update plot title and labels for Daily Attempts
        ax.set_title(f'Daily Attempts on Segment: {segment_name} ({segment_id})')
        ax.set_xlabel('Date')
        ax.set_ylabel('Attempts Recorded That Day') # Updated label
        ax.grid(True, which='both', linestyle='--', linewidth=0.5)
        ax.set_ylim(bottom=0) # Ensure y-axis starts at 0

        # Format x-axis dates
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=12))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=30, ha='right')

        plt.tight_layout()
        plt.savefig(plot_filepath)
        print(f"Plot saved to '{plot_filepath}'")
        plt.close(fig) # Close the plot figure to free memory

    except pd.errors.EmptyDataError:
        print(f"Plotting skipped: Master CSV file '{MASTER_CSV_FILE}' is empty (pandas EmptyDataError).")
    except KeyError as e:
        print(f"Plotting skipped for segment {segment_id}: Missing expected column ({e}) in '{MASTER_CSV_FILE}'. Check header/data.")
    except Exception as e:
        print(f"ERROR generating plot for segment {segment_id}: {e}")


# --- Main Execution Logic ---
if __name__ == "__main__":
    start_time = datetime.datetime.now()
    print(f"--- Strava Segment Tracker Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')} ---")

    # 1. Load Configuration
    app_config = load_config()
    segment_ids_to_process = app_config['segment_id_list']
    print(f"\nFound {len(segment_ids_to_process)} segment(s) to process: {', '.join(segment_ids_to_process)}")

    # 2. Get Fresh Access Token
    access_token = refresh_access_token(app_config)

    # 3. Loop through each Segment ID to fetch current data
    processed_count = 0
    error_count = 0
    all_segment_data_current = [] # Store currently fetched data

    print("\n--- Fetching Current Segment Data ---")
    for segment_id in segment_ids_to_process:
        segment_start_time = time.time()
        print(f"\nProcessing Segment ID: {segment_id}")
        try:
            segment_data = get_segment_data(segment_id, access_token)
            if segment_data:
                all_segment_data_current.append(segment_data)
                processed_count += 1
            else:
                print(f"Skipping segment {segment_id} due to data fetch failure.")
                error_count += 1

        except Exception as e:
            print(f"!! UNEXPECTED ERROR fetching data for segment {segment_id}: {e}")
            error_count += 1
            # Attempt to continue with the next segment
        segment_end_time = time.time()
        print(f"Finished fetching for {segment_id} (took {segment_end_time - segment_start_time:.2f} seconds)")

    # 4. Update Log File and Generate Plots (after fetching all data)
    print(f"\n--- Updating Log File: {MASTER_CSV_FILE} ---")
    if not all_segment_data_current:
        print("No segment data fetched successfully. Skipping log update and plotting.")
    else:
        # Update the master log file sequentially for each fetched segment
        for segment_data in all_segment_data_current:
             update_master_log(segment_data) # This calculates daily diff based on file history

        print(f"\n--- Generating Plots (Output to '{PLOT_DIR}/') ---")
        # Generate plots using the now updated master log file
        for segment_data in all_segment_data_current:
            generate_plot(segment_data['id'], segment_data['name'])


    # --- Summary ---
    end_time = datetime.datetime.now()
    print(f"\n--- Strava Segment Tracker Finished: {end_time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    print(f"Total execution time: {end_time - start_time}")
    print(f"Segments processed successfully: {processed_count}")
    print(f"Segments failed/skipped: {error_count}")