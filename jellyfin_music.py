import datetime
import math
import pickle
import random
import sys
import pandas as pd
import requests
import os
from dotenv import load_dotenv

pd.options.mode.copy_on_write = True  # to avoid the SettingWithCopyWarning

load_dotenv()

API_KEY = os.getenv('API_KEY')
JELLYFIN_IP = os.getenv('JELLYFIN_IP')
USER_NAME = os.getenv('USER_NAME')
PLAYLIST_LENGTH = int(os.getenv('PLAYLIST_LENGTH')) if os.getenv('PLAYLIST_LENGTH') else 6
PLAYLIST_NAME = os.getenv('PLAYLIST_NAME') if os.getenv('PLAYLIST_NAME') else 'Daily Random Playlist'

CLIENT = 'DailyPlaylistCreator'
DEVICE = 'DailyPlaylistCreator'
VERSION = '1.0.0'

headers = {'Authorization': f'MediaBrowser Client="{CLIENT}", Device="{DEVICE}", '
                            f'Version="{VERSION}", Token="{API_KEY}"'}


# scoring function for the song rank
def score_function(recent_play_normal: float, total_play_count: int, days_since_last_played: int,
                   weights: tuple[float, float, float] = (0.60, 0.25, 0.15), decay_rate: float = 0.5,
                   min_play_threshold: int = 3) -> float:
    if total_play_count < min_play_threshold:
        return 0
    frequency = recent_play_normal
    recency = (1 / (1 + math.e ** (decay_rate * days_since_last_played)))
    high_play_decay = (1/(1+math.log(1+total_play_count, 2)))
    return weights[0] * frequency + weights[1] * recency + weights[2] * high_play_decay


# rank the songs by the play_count and the artist play_count to get songs that have been played a lot recently
def rank_recent(df: pd.DataFrame) -> pd.DataFrame:
    artist_play_count = df.groupby('album_artist')['play_count'].sum()
    artist_play_count = artist_play_count / artist_play_count.sum()
    df['artist_play_count'] = df['album_artist'].map(artist_play_count)
    df['artist_play_count'] = df['artist_play_count'].fillna(0)
    df['rank'] = df['artist_play_count'] * df['play_count']
    df = df.sort_values('rank', ascending=False)
    return df.head(50)


def rank_recent_by_activity(df: pd.DataFrame, list_activity: list, lookup_df) -> pd.DataFrame:
    df['last_7_days'] = 1
    for i in list_activity:
        # check if the song has been played for at least 80% of the song
        try:
            if int(i[2]) <= lookup_df.loc[lookup_df.index == i[1], 'length'].values[0] * 0.8:
                df.loc[df.index == i[1], 'last_7_days'] -= 1
                continue
        except IndexError:
            continue
        df.loc[df.index == i[1], 'last_7_days'] += 1
    df['last_played'] = pd.to_datetime(df['last_played'], utc=True)
    df['days_since_last_played'] = (pd.to_datetime('now', utc=True) - df['last_played']).dt.days
    max_plays_7_days = df['last_7_days'].max()
    df['rank'] = df.apply(lambda x: score_function(x['last_7_days'] / max_plays_7_days, x['play_count'], x['days_since_last_played']),
                          axis=1)
    df = df.sort_values('rank', ascending=False)
    return df.head(50)


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
    request = f"{JELLYFIN_IP}/Users/{user_id}/Items?SortBy=Album,SortName&SortOrder=Ascending" \
              f"&IncludeItemTypes=Audio&Recursive=true&Fields=AudioInfo,ParentId,Path,Genres&StartIndex=0&ImageTypeLimit=1"
    sessions = requests.get(request, headers=headers)
    session_data = sessions.json()
    items = {}
    for i in session_data.get('Items'):
        play_count = i['UserData']['PlayCount']
        try:
            last_played = i['UserData']['LastPlayedDate']
        except KeyError:
            last_played = None
        if 'AlbumId' not in i:
            print("something did not work couldnt find AlbumId in:")
            print(i)

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
        # length in seconds
        length = i['RunTimeTicks'] / 10000000
        items[i['Id']] = {'song_name': song_name, 'play_count': play_count, 'last_played': last_played, 'path': path,
                          'album_id': album_id, 'album_artist': album_artist, 'is_favorite': is_favorite,
                          'length': length, 'genre': genre}
    return items


# returns the listen data for all audio items
def get_listen_data(user_id: str) -> list:
    # get all audio data
    request = f"{JELLYFIN_IP}/user_usage_stats/submit_custom_query"
    data = {'CustomQueryString': 'SELECT DateCreated, ItemId, PlayDuration '
                                 'FROM PlaybackActivity '
                                 f'WHERE UserId="{user_id}" '
                                 f'AND ItemType="Audio" '
                                 # f'AND DateCreated >= DATE("now", "-{days} days") '
                                 'ORDER BY DateCreated DESC ',
            'ReplaceUserId': False}
    sessions = requests.post(request, headers=headers, json=data)
    # check if the request was successful
    if sessions.status_code != 200:
        print("Playback Reporting not available. Skipping this step.")
        return []
    session_data = sessions.json()

    if not session_data['results']:
        return []
    return session_data['results']


# check if the song has been listened to for long enough to be considered as listened to
def check_single_song(song_id: str, listen_data: list, total_length: int) -> bool:
    if not listen_data:
        return True
    listen_data = [i for i in listen_data if i[1] == song_id]
    try:
        # get the average play duration across all plays and check if the song
        # has been played for at least 80% of the song
        return sum([int(i[2]) for i in listen_data]) / len(listen_data) >= total_length * 0.8
    except IndexError:
        return True
    except ZeroDivisionError:
        return True


def check_single_song_by_skip(song_id: str, listen_data: list, total_length: int, total_plays: int) -> bool:
    # if there is no listen data, assume that the song is good
    if not listen_data:
        return True

    listen_data = [i for i in listen_data if i[1] == song_id]

    # listen_data must exist but no entries for song means that it was skipped every time
    if not listen_data:
        return False

    for i, p in enumerate(listen_data):
        if min(total_length, int(p[2])) < total_length * 0.8:
            listen_data[i] = listen_data[i] + ["skip"]
        else:
            listen_data[i] = listen_data[i] + ["listen"]

    # assume that the list is sorted by date in descending order
    # if the user listened to it last time, they probably like it, at worst it's a false positive
    try:
        if (listen_data[0][3] == "listen") or (len(listen_data) < 3 and total_plays < 3):
            return True
    except IndexError:
        return True

    # if the user skipped it last time, we have to check if they usually listen to it
    # if they skipped it the last 3 times, they probably don't like it
    if set([i[3] for i in listen_data[:3]]) == {"skip"}:
        return False

    # return the majority of the all plays, if it's a tie, return True
    return len([i[3] for i in listen_data if i[3] == "listen"]) > total_plays // 2


def get_similar(song_id: str) -> list:
    request = f"{JELLYFIN_IP}/Items/{song_id}/similar"
    sessions = requests.get(request, headers=headers)
    session_data = sessions.json()
    similar = [i['Id'] for i in session_data.get('Items')]
    return similar


def random_songs_by_attribute(song_df: pd.DataFrame, attribute: str, a: int, b: int) -> list:
    # get the artists of daily_playlist_items and for each one get a-b songs randomly
    selected_songs = []
    artists = song_df.loc[:, attribute].unique()
    try:
        for artist in artists:
            attribute_songs = song_df[song_df[attribute] == artist].index
            if len(attribute_songs) < a:
                selected_songs.extend(attribute_songs)
                continue
            selected_songs.extend([random.choice(attribute_songs) for _ in range(random.randint(a, b))])
    except KeyError:
        pass
    return selected_songs


def random_songs_by_play_count(song_df: pd.DataFrame, min_play_count: int, max_play_count: int, a: int, b: int) -> list:
    try:
        rest_songs = song_df[(song_df['play_count'] > min_play_count) & (song_df['play_count'] < max_play_count)].index
        return [random.choice(rest_songs) for _ in range(random.randint(a, b))]
    except KeyError:
        return []


def random_stuffing(daily_playlist_items: list, extra: int = 5) -> list:
    # just add some similar songs from a random song in the playlist
    return get_similar(random.choice(daily_playlist_items[:min(10, len(daily_playlist_items))]))[:extra]


def culminate_potential_songs(song_df: pd.DataFrame, listen_data: list) -> list:
    daily_playlist_items = []
    # convert date to datetime
    song_df.loc[:, 'last_played'] = pd.to_datetime(song_df.loc[:, 'last_played'])

    df = song_df.sort_values('last_played', ascending=False)
    top_latest = rank_recent_by_activity(df.head(100), listen_data, df) if listen_data else rank_recent(df.head(100))

    # i dont know why but sample doesn't work when there are less nonzero values than n
    top_latest_nonzero = top_latest[top_latest['rank'] > 0]
    sample_size = min(20, len(top_latest_nonzero))
    # add 10 songs from the top_latest to daily_playlist_items with weights where weights are the rank
    daily_playlist_items.extend(top_latest.sample(n=sample_size, weights='rank').index)

    similars = []
    # for each song in daily_playlist_items, get 3 similar songs, this is probably lighter than doing it for 50 songs
    for i in top_latest.index:
        similar = get_similar(i)
        similars.extend(similar[:3])
    daily_playlist_items.extend(similars)

    # for the five best artists, get at max 5 songs as the other songs will likely come by the other methods
    top_artists = top_latest['album_artist'].value_counts().head(5).index
    for artist in top_artists:
        artist_songs = df[df['album_artist'] == artist].index
        daily_playlist_items.extend([random.choice(artist_songs) for _ in range(random.randint(3, 5))])

    # add 5-8 random songs from top_latest to daily_playlist_items
    daily_playlist_items.extend([random.choice(top_latest.index) for _ in range(random.randint(5, 8))])

    # get 0 - 5 random songs from the favourites
    try:
        favourites = df[df['is_favorite']].index
        daily_playlist_items.extend([random.choice(favourites) for _ in range(random.randint(0,
                                                                                             min(len(favourites), 5)))])
    except KeyError:
        pass

    # some issue with the daily_playlist_items, so we need to get the working keys
    relevant_ids = df.index.intersection(daily_playlist_items)
    attribute_df = df.loc[relevant_ids]

    # for each artist in daily_playlist_items, get 7-10 songs randomly
    daily_playlist_items.extend(random_songs_by_attribute(attribute_df, 'album_artist', 7, 10))

    # for each album in daily_playlist_items, get 7-10 songs randomly
    daily_playlist_items.extend(random_songs_by_attribute(attribute_df, 'album_id', 7, 10))

    # get 10-15 random songs from the rest of the songs where play_count > 3
    daily_playlist_items.extend(random_songs_by_play_count(df, 3, 99, 10, 15))

    # get 5-10 random songs from the rest of the songs where play_count <= 3
    daily_playlist_items.extend(random_songs_by_play_count(df, -1, 4, 5, 10))

    # mix the daily_playlist_items while retaining the order of the first 10 songs
    try:
        daily_playlist_items = daily_playlist_items[:20] + random.sample(daily_playlist_items[20:],
                                                                         len(daily_playlist_items) - 20)
    except ValueError:
        pass

    print(f"Playlist has {len(daily_playlist_items)} items before pruning.")
    return daily_playlist_items


# remove songs that are duplicated or probably unfit for the playlist
def prune_playlist(song_df: pd.DataFrame, listen_data: list, daily_playlist_items: list, length: int) -> list:

    # check and remove duplicates without using set to retain order
    daily_playlist_items = [i for n, i in enumerate(daily_playlist_items) if i not in daily_playlist_items[:n]]

    if listen_data:
        to_remove = []
        for i in daily_playlist_items[:20]:
            if song_df.loc[i, 'play_count'] < 1:
                continue
            if not check_single_song_by_skip(i, listen_data, song_df.loc[i, 'length'], song_df.loc[i, 'play_count']):
                to_remove.append(i)
        daily_playlist_items = [i for i in daily_playlist_items if i not in to_remove]

    # limit or stuff the playlist to 6 hours
    playlist_length = sum([song_df.loc[i, 'length'] for i in daily_playlist_items])

    # if the playlist is too short, add more songs that are similar to the first few
    extension_constant = 5
    while playlist_length < length:
        stuff_songs = random_stuffing(daily_playlist_items, extension_constant)
        stuff_songs = [x for x in stuff_songs if x not in daily_playlist_items and x in song_df.index]

        if listen_data:
            stuff_songs = [i for i in stuff_songs if check_single_song_by_skip(i, listen_data, song_df.loc[i, 'length'],
                                                                               song_df.loc[i, 'play_count'])]
        daily_playlist_items.extend(stuff_songs)
        playlist_length = sum([song_df.loc[i, 'length'] for i in daily_playlist_items])
        extension_constant += 1

    # if the playlist is too long, remove the last songs
    while playlist_length > length:
        # remove the last song
        daily_playlist_items.pop()
        playlist_length = sum([song_df.loc[i, 'length'] for i in daily_playlist_items])

    print(
        f"Final playlist has {len(daily_playlist_items)} items and is {playlist_length / 60 / 60:.2f} hours long.")
    return daily_playlist_items


def create_random_playlist(song_df: pd.DataFrame, listen_data: list, recency: int = 7, length: int = 360000) -> list:
    # extract the last n days of listen data
    n_days_ago = datetime.datetime.now() - datetime.timedelta(days=recency)
    # remove the microseconds because I'm not dealing with this garbage
    recent_listen_data = [i for i in listen_data if
                          datetime.datetime.strptime(i[0].split(".")[0], '%Y-%m-%d %H:%M:%S') > n_days_ago]
    
    if len(recent_listen_data) == 0:
        try:
            recent_listen_data = listen_data[:100]
        except IndexError:
            recent_listen_data = []

    daily_playlist_items = culminate_potential_songs(song_df, recent_listen_data)
    # pruning the list
    daily_playlist_items = prune_playlist(song_df, listen_data, daily_playlist_items, length)
    return daily_playlist_items


def create_jellyfin_playlist(user_id: str, playlist_name: str, playlist_items: list) -> int:
    # get all playlists and filter for the playlist_name, if it exists, delete it
    request = f"{JELLYFIN_IP}/Users/{user_id}/Items?IncludeItemTypes=Playlist&Recursive=true"
    sessions = requests.get(request, headers=headers)
    session_data = sessions.json()
    for i in session_data['Items']:
        if i['Name'] == playlist_name:
            print("Playlist exists, deleting it")
            request = f"{JELLYFIN_IP}/Items/{i['Id']}"
            sessions = requests.delete(request, headers=headers)
            if sessions.status_code != 204:
                print("Error deleting playlist:", sessions.status_code)
                return sessions.status_code

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
              ".example.env file in the same directory as this script and fill it in with your values. "
              "Then rename it to .env.")
        sys.exit(1)
    # acquire necessary data
    user_id = get_users(USER_NAME)
    song_data = get_all_songs(user_id)
    listen_data = get_listen_data(user_id)
    # pickle.dump(song_data, open('example_song_data.pkl', 'wb'))
    # song_data = pickle.load(open('example_song_data.pkl', 'rb'))

    # create the playlist
    playlist = create_random_playlist(pd.DataFrame(song_data).T, listen_data, 7, PLAYLIST_LENGTH * 60 * 60)
    playlist_status = create_jellyfin_playlist(user_id, PLAYLIST_NAME, playlist)
    if playlist_status == 200:
        print("Playlist created successfully:", playlist_status)
    else:
        print("Playlist creation failed:", playlist_status)
