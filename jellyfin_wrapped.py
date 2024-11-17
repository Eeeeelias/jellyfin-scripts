import math
import os
import sys
from io import BytesIO
import requests
from dotenv import load_dotenv
import pandas as pd
from collections import Counter
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math
import matplotlib.colors as mcolors

load_dotenv()

API_KEY = os.getenv('API_KEY')
JELLYFIN_IP = os.getenv('JELLYFIN_IP')
USER_NAME = os.getenv('USER_NAME')

CLIENT = 'JellyfinWrapped'
DEVICE = 'JellyfinWrapped'
VERSION = '1.0.0'

headers = {'Authorization': f'MediaBrowser Client="{CLIENT}", Device="{DEVICE}", '
                            f'Version="{VERSION}", Token="{API_KEY}"'}


def get_users(user=None) -> dict | str:
    sessions = requests.get(f"{JELLYFIN_IP}/Users", headers=headers)
    session_data = sessions.json()
    users = {}
    for i in session_data:
        users[i['Id']] = i['Name']
        if i['Name'] == user:
            return i['Id']
    return users


def get_all_songs(user_id: str) -> dict:
    request = f"{JELLYFIN_IP}/Users/{user_id}/Items?SortBy=Album,SortName&SortOrder=Ascending&" \
              f"IncludeItemTypes=Audio&Recursive=true&Fields=AudioInfo,ParentId,Path,Genres&StartIndex=0&ImageTypeLimit=1&" \
              f"ParentId=7e64e319657a9516ec78490da03edccb"
    sessions = requests.get(request, headers=headers)
    session_data = sessions.json()
    items = {}
    print("Songs:", len(session_data.get('Items')))
    for i in session_data.get('Items'):
        play_count = i['UserData']['PlayCount']
        try:
            last_played = i['UserData']['LastPlayedDate']
        except KeyError:
            last_played = None
        album_id = i['AlbumId']
        try:
            album_artist = i['AlbumArtist']
            if album_artist == 'Various Artists':
                album_artist = i['Artists'][0]
            artist_id = i['AlbumArtists'][0]['Id']
        except:
            album_artist = None
        is_favorite = i['UserData']['IsFavorite']
        song_name = i['Name']
        path = i['Path']
        genre = i['Genres']
        # length in seconds
        length = i['RunTimeTicks'] / 10000000
        items[i['Id']] = {'song_name': song_name, 'play_count': play_count, 'last_played': last_played, 'path': path,
                          'album_id': album_id, 'album_artist': album_artist, 'is_favorite': is_favorite,
                          'length': length, 'genre': genre, 'artist_id': artist_id}
    return items


def retrieve_last_time_audio(user_id: str = None, duration='month'):
        durations = {
            'year': 365,
            'month': 31,
            'week': 7,
        }
        days_duration = durations[duration]
        request = f"{JELLYFIN_IP}/user_usage_stats/submit_custom_query"
        data = {'CustomQueryString': 'SELECT DateCreated, ItemId, PlayDuration '
                                     'FROM PlaybackActivity '
                                     f'WHERE UserId="{user_id}" '
                                     f'AND ItemType="Audio" '
                                     f'AND DateCreated >= DATE("now", "-{days_duration} days") '
                                     'ORDER BY DateCreated DESC ',
                'ReplaceUserId': False}
        sessions = requests.post(request, headers=headers, json=data)
        # check if the request was successful
        if sessions.status_code != 200:
            print("No Playback Reporting. Make sure it is installed")
            sys.exit(1)
        session_data = sessions.json()

        if not session_data['results']:
            return []
        return session_data['results']


def retrieve_artist_img(artist_id: str = None):
    request = f"{JELLYFIN_IP}/Items/{artist_id}/Images/Primary?fillHeight=500&fillWidth=500&quality=96"
    response = requests.get(request, headers=headers)
    if response.status_code != 200:
        print("Could not find artist")
        return None
    return BytesIO(response.content)


def rank_by_most_listened(all_songs: pd.DataFrame, listen_data: pd.DataFrame):
    relevant_items = set(listen_data['item_id'])
    all_songs = all_songs[all_songs.index.isin(relevant_items)]
    song_play_count = Counter(listen_data['item_id'])
    all_songs['play_count'] = all_songs.index.map(song_play_count)
    artist_play_count = all_songs.groupby('album_artist')['play_count'].sum()
    artist_play_count = artist_play_count.sort_values(ascending=False)
    return artist_play_count

def best_songs_by_artist(all_songs: pd.DataFrame, listen_data: pd.DataFrame, artist_id: str):
    relevant_items = set(listen_data['item_id'])
    all_songs = all_songs[all_songs.index.isin(relevant_items)]
    song_play_count = Counter(listen_data['item_id'])
    all_songs['play_count'] = all_songs.index.map(song_play_count)
    artist_play_count = all_songs[all_songs['artist_id'] == artist_id]
    artist_play_count = artist_play_count.sort_values('play_count', ascending=False)
    return artist_play_count


def total_play_time(listen_data: pd.DataFrame, all_music: pd.DataFrame):
    listen_data['play_duration'] = listen_data['play_duration'].astype(int)
    total_listen_time = 0
    found = 0
    not_found = 0
    for i, row in listen_data.iterrows():
        if row['item_id'] in all_music.index:
            total_listen_time += min(row['play_duration'], all_music.loc[row['item_id']]['length'])
            found += 1
        else:
            not_found += 1
            total_listen_time += min(row['play_duration'], 300)
    print(f"Found songs: {found}, Songs no longer associated with an id: {not_found}")
    total_listen_time = math.ceil(total_listen_time / 60)
    return int(total_listen_time)


def top_genres(all_songs: pd.DataFrame, listen_data: pd.DataFrame):
    relevant_items = set(listen_data['item_id'])
    all_songs = all_songs[all_songs.index.isin(relevant_items)]
    song_play_count = Counter(listen_data['item_id'])
    all_songs['play_count'] = all_songs.index.map(song_play_count)
    all_songs['genre'] = all_songs['genre'].apply(lambda x: ', '.join(x))
    genre_play_count = all_songs.groupby('genre')['play_count'].sum()
    genre_play_count = genre_play_count.sort_values(ascending=False)
    # remove empty genres
    genre_play_count = genre_play_count[genre_play_count.index != '']
    return genre_play_count


def get_data():
    user_id = get_users(USER_NAME)
    all_music = get_all_songs(user_id)
    audio = retrieve_last_time_audio(user_id, duration='year')
    listen_data = pd.DataFrame(audio, columns=['date_created', 'item_id', 'play_duration'])
    all_music = pd.DataFrame(all_music).T
    best_artists = rank_by_most_listened(all_music, listen_data)
    # for the best artist, get the image
    artist_id = all_music[all_music['album_artist'] == best_artists.index[0]].iloc[0]['artist_id']
    artist_img = retrieve_artist_img(artist_id)
    best_songs = best_songs_by_artist(all_music, listen_data, artist_id)['song_name'][0:5]
    # output_image = make_info_image(artist_img, best.index[0], best.iloc[0], best_songs)
    total_listen_time = total_play_time(listen_data, all_music)
    genres = top_genres(all_music, listen_data)[0:5]

    # Save or display the output image (for example, to a file or in a notebook)
    # output_image.show()  # To display the image
    return list(best_artists[0:5].index), list(best_songs), total_listen_time, list(genres.index), artist_img


JF_COLOR = "#000B25"
CMAP = mcolors.LinearSegmentedColormap.from_list("", ["#AA5CC3", "#00A4DC"])

def add_rounded_corners(image, radius):
    # Create a mask for the image with rounded corners
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, image.size[0], image.size[1]),
        radius=radius,
        fill=255
    )
    # Apply the mask to the image
    rounded_image = Image.new("RGBA", image.size)
    rounded_image.paste(image, mask=mask)
    return rounded_image


def add_shadow(canvas, image, position, shadow_offset=(10, 10), shadow_radius=15, shadow_color=(0, 0, 0, 100)):
    # Create a mask for the image with rounded corners
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, image.size[0], image.size[1]),
        radius=min(image.size) // 10,  # Corner radius
        fill=255
    )

    # Create a shadow by blurring the mask
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.bitmap(
        (position[0] + shadow_offset[0], position[1] + shadow_offset[1]),
        mask,
        fill=shadow_color
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_radius))

    # Paste the shadow onto the canvas
    canvas.alpha_composite(shadow)


def image_with_gradient(canvas_size):
    image = Image.new('RGB', canvas_size, color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    # Get the dimensions
    width, height = canvas_size

    # Create a gradient
    for y in range(height):
        for x in range(width):
            # Calculate the interpolation value
            t = ((x / width) + (y / height)) / 2  # Gradient diagonal
            r, g, b, _ = CMAP(t)  # Get color from colormap
            color = (int(r * 255), int(g * 255), int(b * 255))  # Convert to RGB
            draw.point((x, y), fill=color)

    return image


def add_text(canvas, text, position, column_end=None, bold_font=False, font_size=30, color=(255, 255, 255)):
    draw = ImageDraw.Draw(canvas)
    try:
        font_path = "Helvetica.ttf"
        font_bold_path = font_path.replace(".ttf", "-Bold.ttf")

        if bold_font:
            font = ImageFont.truetype(font_bold_path, font_size)
        else:
            font = ImageFont.truetype(font_path, font_size)
    except IOError:
        font = ImageFont.load_default()  # Fallback to default font if specified font is unavailable

    # Calculate the width and height of the text
    bounding_box = draw.textbbox(position, text, font=font)

    # If a column end is specified, cut the text off at the column end
    if column_end:
        text_width = bounding_box[2] - bounding_box[0]
        while text_width > column_end - position[0]:
            if text.endswith("..."):
                text = text[:-4] + "..."
            else:
                text = text[:-3] + "..."
            bounding_box = draw.textbbox(position, text, font=font)
            text_width = bounding_box[2] - bounding_box[0]

    text_position = position

    # Add the text to the canvas
    draw.text(text_position, text, fill=color, font=font)


def make_info_image(artist_img, artist_names, play_time, song_names, top_genre, canvas_size=(600, 1100)):
    image = Image.open(artist_img)
    logo = Image.open('jellyfin_logo.png')
    canvas = image_with_gradient(canvas_size).convert('RGBA')

    # Resize the image to fit within the center of the canvas, keeping the aspect ratio
    max_image_width = canvas_size[0] * 0.8
    max_image_height = canvas_size[1] * 0.5

    logo_image_width = canvas_size[0] * 0.3
    logo_image_height = canvas_size[1] * 0.2

    image.thumbnail((max_image_width, max_image_height), Image.HUFFMAN_ONLY)
    logo.thumbnail((logo_image_width, logo_image_height), Image.HUFFMAN_ONLY)

    # Add rounded corners to the image
    corner_radius = min(image.size) // 20
    image_with_corners = add_rounded_corners(image, corner_radius)

    # Calculate the position to center the image
    image_x = (canvas_size[0] - image_with_corners.width) // 2
    image_y = 20 # fixed position from top
    image_position = (image_x, image_y)

    logo_x = 20
    logo_y = (canvas_size[1] - logo.height) - 20
    logo_position = (logo_x, logo_y)

    first_column_x_start = 50
    first_column_x_end = canvas_size[0] // 2 - 20
    second_column_x_start = canvas_size[0] // 2 + 20
    second_column_x_end = canvas_size[0] - 50

    first_row_y = (canvas_size[1] // 2) + 30

    # Add text to the canvas
    # first row
    add_text(canvas, "Top Artists", position=(first_column_x_start, first_row_y), font_size=30, color=(0, 0, 0))
    add_text(canvas, "Top Songs", position=(second_column_x_start, first_row_y), font_size=30, color=(0, 0, 0))
    for i, artist_name in enumerate(artist_names):
        add_text(canvas, f"{i + 1} {artist_name}", position=(first_column_x_start, first_row_y + 50 + i * 40),
                 column_end=first_column_x_end, bold_font=True, font_size=30, color=(0, 0, 0))

    for i, song_name in enumerate(song_names):
        add_text(canvas, f"{i + 1} {song_name}", position=(second_column_x_start, first_row_y + 50 + i * 40),
                 bold_font=True, column_end=second_column_x_end, font_size=30, color=(0, 0, 0))

    # second row
    second_row_y = first_row_y + 50 + len(artist_names) * 40 + 50

    add_text(canvas, "Minutes played", position=(first_column_x_start, second_row_y), font_size=30, color=(0, 0, 0))
    add_text(canvas, f"{play_time:,}", position=(first_column_x_start, second_row_y + 50), bold_font=True, font_size=40, color=(0, 0, 0))

    add_text(canvas, "Top Genre", position=(second_column_x_start, second_row_y), font_size=30, color=(0, 0, 0))
    add_text(canvas, top_genre, position=(second_column_x_start, second_row_y + 50), bold_font=True, font_size=40, color=(0, 0, 0))

    # Add a light shadow
    add_shadow(canvas, image_with_corners, image_position, shadow_offset=(10, 10), shadow_radius=15)

    # Paste the image with rounded corners onto the canvas
    canvas.paste(image_with_corners, image_position, mask=image_with_corners.split()[3])
    canvas.paste(logo, logo_position, mask=logo.split()[3])

    return canvas


if __name__ == '__main__':
    if not API_KEY or not JELLYFIN_IP or not USER_NAME:
        print("Please set the API_KEY, JELLYFIN_IP and USER_NAME environment variables.\nTo do this, make a copy of the"
              ".example.env file in the same directory as this script and fill it in with your values. "
              "Then rename it to .env.")
        sys.exit(1)

    if not os.path.exists("jellyfin_logo.png"):
        print("Couldn't find jellyfin logo. Please download jellyfin logo as 'jellyfin_logo.png' so that it can be "
              "added to the wrapped")
        sys.exit(1)

    # first get the data from the jellyfin_song_summary.py
    best_artists, best_songs, total_listen_time, best_genres, artist_img = get_data()
    logo_data = 'jellyfin_logo.png'

    out = make_info_image(artist_img, best_artists, total_listen_time, best_songs, 'Soundtrack')

    out.save('jellyfin_wrapped.png')
    out.show()
