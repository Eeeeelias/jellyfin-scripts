import pickle
import random
import sys

import pandas as pd
import requests
import os
from dotenv import load_dotenv


load_dotenv()

### Change this to your own values ###
API_KEY = os.getenv('API_KEY')
JELLYFIN_IP = os.getenv('JELLYFIN_IP')
USER_NAME = os.getenv('USER_NAME')
PLAYLIST_LENGTH = int(os.getenv('PLAYLIST_LENGTH')) if os.getenv('PLAYLIST_LENGTH') else 6
PLAYLIST_NAME = os.getenv('PLAYLIST_NAME') if os.getenv('PLAYLIST_NAME') else 'Daily Random Playlist'

### These should just work ###
CLIENT = 'DailyPlaylistCreator'
DEVICE = 'DailyPlaylistCreator'
VERSION = '1.0.0'

headers = {'Authorization': f'MediaBrowser Client="{CLIENT}", Device="{DEVICE}", '
                            f'Version="{VERSION}", Token="{API_KEY}"'}


# rank the songs by the play_count and the artist play_count to get songs that have been played a lot recently
def rank_recent(df: pd.DataFrame) -> pd.DataFrame:
    artist_play_count = df.groupby('album_artist')['play_count'].sum()
    artist_play_count = artist_play_count / artist_play_count.sum()
    df['artist_play_count'] = df['album_artist'].map(artist_play_count)
    df['artist_play_count'] = df['artist_play_count'].fillna(0)
    df['rank'] = df['artist_play_count'] * df['play_count']
    df = df.sort_values('rank', ascending=False)
    return df.head(50)


def get_users(user=None) -> dict:
    sessions = requests.get(f"{JELLYFIN_IP}/Users", headers=headers)
    session_data = sessions.json()
    users = {}
    for i in session_data:
        users[i['Id']] = i['Name']
        if i['Name'] == user:
            return i['Id']
    return users


def get_all_songs(user_id) -> dict:
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
        except:
            album_artist = None
        is_favorite = i['UserData']['IsFavorite']
        song_name = i['Name']
        path = i['Path']
        genre = i['Genres']
        items[i['Id']] = {'song_name': song_name, 'play_count': play_count, 'last_played': last_played, 'path': path,
                          'album_id': album_id, 'album_artist': album_artist, 'is_favorite': is_favorite,
                          'length': i['RunTimeTicks'],
                          'genre': genre}
    return items


def get_similar(song_id) -> list:
    request = f"{JELLYFIN_IP}/Items/{song_id}/similar"
    sessions = requests.get(request, headers=headers)
    session_data = sessions.json()
    similar = [i['Id'] for i in session_data.get('Items')]
    return similar


def create_random_playlist(song_df, length=360000) -> list:
    daily_playlist_items = []
    # convert date to datetime
    song_df['last_played'] = pd.to_datetime(song_df['last_played'])

    df = song_df.sort_values('last_played', ascending=False)

    top_latest = rank_recent(df.head(100))
    for i in top_latest.index:
        similar = get_similar(i)
        daily_playlist_items.extend(similar[:3])
    # for the five best artists, get at max 5 songs as the other songs will likely come by the other methods
    top_artists = top_latest['album_artist'].value_counts().head(5).index
    for artist in top_artists:
        artist_songs = df[df['album_artist'] == artist].index
        daily_playlist_items.extend([random.choice(artist_songs) for _ in range(random.randint(3, 5))])

    # add 5-8 random songs from top_latest to daily_playlist_items
    daily_playlist_items.extend([random.choice(top_latest.index) for _ in range(random.randint(5, 8))])

    # get 0 - 5 random songs from the favourites
    favourites = df[df['is_favorite']].index
    daily_playlist_items.extend([random.choice(favourites) for _ in range(random.randint(0, 5))])

    # some issue with the daily_playlist_items, so we need to get the working keys
    working = df.index.intersection(daily_playlist_items)
    print(len(working), len(daily_playlist_items))

    # get the artists of daily_playlist_items and for each one get 7-10 songs randomly
    artists = df.loc[working, 'album_artist'].unique()
    for artist in artists:
        artist_songs = df[df['album_artist'] == artist].index
        daily_playlist_items.extend([random.choice(artist_songs) for _ in range(random.randint(7, 10))])

    # get the albums of daily_playlist_items and for each one get 7-10 songs randomly
    albums = df.loc[working, 'album_id'].unique()
    for album in albums:
        album_songs = df[df['album_id'] == album].index
        daily_playlist_items.extend([random.choice(album_songs) for _ in range(random.randint(7, 10))])

    # get 10-15 random songs from the rest of the songs where playcount > 3
    rest_songs = df[df['play_count'] > 3].index
    daily_playlist_items.extend([random.choice(rest_songs) for _ in range(random.randint(10, 15))])

    # get 5-10 random songs from the rest of the songs where playcount <= 3
    rest_songs = df[df['play_count'] <= 3].index
    daily_playlist_items.extend([random.choice(rest_songs) for _ in range(random.randint(5, 10))])

    # mix the daily_playlist_items while retaining the order of the first 10 songs
    daily_playlist_items = daily_playlist_items[:10] + random.sample(daily_playlist_items[10:],
                                                                     len(daily_playlist_items) - 10)

    # check and remove duplicates without using set to retain order
    daily_playlist_items = [i for n, i in enumerate(daily_playlist_items) if i not in daily_playlist_items[:n]]

    # limit the playlist to 6 hours
    playlist_length = sum([song_df.loc[i, 'length'] for i in daily_playlist_items])
    while playlist_length > length:
        daily_playlist_items.pop()
        playlist_length = sum([song_df.loc[i, 'length'] for i in daily_playlist_items])

    print(f"Final playlist has {len(daily_playlist_items)} items and is {playlist_length / 10000000 / 60 / 60:.2f} hours long.")
    return daily_playlist_items


def create_jellyfin_playlist(user_id, playlist_name, playlist_items) -> int:
    # get all playlists and filter for the playlist_name, if it exists, delete it
    request = f"{JELLYFIN_IP}/Users/{user_id}/Items?parentId=821d3a92eeb242a0a3a67a6e7fafe481"
    sessions = requests.get(request, headers=headers)
    session_data = sessions.json()
    for i in session_data['Items']:
        if i['Name'] == playlist_name:
            print("Playlist exists, deleting it")
            request = f"{JELLYFIN_IP}/Items/{i['Id']}"
            sessions = requests.delete(request, headers=headers)
            if sessions.status_code == 204:
                print("Playlist deleted successfully")

    request = f"{JELLYFIN_IP}/Playlists"
    data = {
        "Name": playlist_name,
        "Ids": playlist_items,
        "UserId": user_id,
    }
    sessions = requests.post(request, headers=headers, json=data)
    # return response code
    return sessions.status_code


if __name__ == '__main__':
    if not API_KEY or not JELLYFIN_IP or not USER_NAME:
        print("Please set the API_KEY, JELLYFIN_IP and USER_NAME environment variables.\nTo do this, make a copy of the"
              ".example.env file in the same directory as this script and fill it in with your values. Then rename it to .env.")
        sys.exit(1)
    user_id = get_users(USER_NAME)
    song_data = get_all_songs(user_id)
    # pickle.dump(song_data, open('example_song_data.pkl', 'wb'))
    # song_data = pickle.load(open('example_song_data.pkl', 'rb'))
    playlist = create_random_playlist(pd.DataFrame(song_data).T, PLAYLIST_LENGTH * 60 * 60 * 10000000)
    playlist_status = create_jellyfin_playlist(user_id, PLAYLIST_NAME, playlist)
    if playlist_status == 200:
         print("Playlist created successfully:", playlist_status)
    else:
         print("Playlist creation failed:", playlist_status)
