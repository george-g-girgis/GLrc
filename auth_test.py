import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

def test_auth():
    print("Testing Spotify Authentication...")
    
    # We need scopes to read playback state
    scope = "user-read-currently-playing user-read-playback-state"
    
    # Initialize SpotifyOAuth
    # Since we use dotenv, spotipy automatically picks up SPOTIPY_CLIENT_ID, 
    # SPOTIPY_CLIENT_SECRET, and SPOTIPY_REDIRECT_URI from the environment variables.
    sp_oauth = SpotifyOAuth(
        scope=scope,
        cache_path=".cache",
        open_browser=True  # Ensure a browser is opened for the initial login
    )
    
    sp = spotipy.Spotify(auth_manager=sp_oauth)
    
    try:
        # Request the currently playing track
        current_playback = sp.current_user_playing_track()
        
        if current_playback and current_playback.get("item"):
            item = current_playback["item"]
            track_name = item["name"]
            artist_name = item["artists"][0]["name"]
            print(f"\n✅ Success! Currently playing: '{track_name}' by {artist_name}")
        else:
            print("\n✅ Success! Authentication worked, but no track is currently playing on Spotify.")
            
    except spotipy.oauth2.SpotifyOauthError as e:
        print(f"\n❌ Authentication failed. Please check your .env credentials. Error: {e}")
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")

if __name__ == "__main__":
    test_auth()
