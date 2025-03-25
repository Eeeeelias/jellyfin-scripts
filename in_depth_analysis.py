from jellyfin_wrapped import get_data
from matplotlib import pyplot as plt
import matplotlib.colors as mcolors
import seaborn as sns
import pandas as pd

JF_COLOR = "#000B25"
CMAP = mcolors.LinearSegmentedColormap.from_list("", ["#AA5CC3", "#00A4DC"])

best_artists, best_songs, total_listen_time, best_genres, artist_img, all_music, listen_data = get_data(get_raw=True)


def listen_timeline(listen_data, save=False):
    timeline_data = listen_data.copy()
    # make sure the play_duration does not exceed the length of the song otherwise cap it at 5 minutes
    for i, row in timeline_data.iterrows():
        if row['item_id'] in all_music.index:
            timeline_data.at[i, 'play_duration'] = min(row['play_duration'], all_music.loc[row['item_id']]['length'])
        else:
            timeline_data.at[i, 'play_duration'] = min(row['play_duration'], 300)

    timeline_data['date_created'] = pd.to_datetime(timeline_data['date_created'])
    timeline_data = timeline_data.set_index('date_created')
    timeline_data = timeline_data.resample('D').sum()
    timeline_data['play_duration'] = timeline_data['play_duration'] / 60

    timeline_data['smoothed_play_duration'] = timeline_data['play_duration'].rolling(window=3, center=True).mean()
    timeline_data['smoothed_play_duration'].fillna(timeline_data['play_duration'], inplace=True)

    plt.figure(figsize=(15, 5))
    plt.grid(axis='y', linestyle='--', alpha=0.6)
    sns.lineplot(data=timeline_data, x=timeline_data.index, y='smoothed_play_duration', color=JF_COLOR)
    # creating a gradient here
    x = timeline_data.index
    y = timeline_data['smoothed_play_duration']
    time_numeric = (timeline_data.index - timeline_data.index[0]).total_seconds()
    time_norm = mcolors.Normalize(vmin=time_numeric.min(), vmax=time_numeric.max())
    for i in range(len(x) - 1):
        plt.fill_between(
            [x[i], x[i + 1]], [y[i], y[i + 1]],
            color=CMAP(time_norm((time_numeric[i] + time_numeric[i + 1]) / 2)),
            alpha=0.8
        )
    plt.title("Minutes listened per day")
    plt.ylabel("Minutes")
    plt.xlabel("Date")

    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()

    if save:
        plt.savefig("listen_timeline.png")

    plt.show()


def most_items(best_artists, best_genres, listen_data, save=False):
    timeline_data = listen_data.copy()
    # remove rows with play duration 0
    timeline_data = timeline_data[timeline_data['play_duration'] > 0]
    song_play_count = timeline_data['item_id'].value_counts().reset_index()
    song_play_count.columns = ['item_id', 'play_count']

    song_df = song_play_count.merge(
        timeline_data[['item_id', 'song_name']].drop_duplicates(),
        on='item_id',
        how='left'
    )
    song_df = song_df[['item_id', 'song_name', 'play_count']]
    song_df = song_df.dropna(subset='song_name')

    # ten colors for the bar plots from the gradient
    colors = [CMAP(i / 10) for i in range(10)]


    fig, ax = plt.subplots(3, 1, figsize=(15, 15))
    sns.barplot(y=best_artists[:10].index, x=best_artists[:10], palette=colors, ax=ax[0])
    ax[0].set_title("Top Artists")
    ax[0].set_xlabel("Play count")
    ax[0].set_ylabel("Artist")

    sns.barplot(y=song_df[:10]['song_name'], x=song_df[:10]['play_count'], palette=colors, ax=ax[1])
    ax[1].set_title("Top Songs")
    ax[1].set_ylabel("Song")
    ax[1].set_xlabel("Play count")

    sns.barplot(y=best_genres[:10].index, x=best_genres[:10], palette=colors, ax=ax[2])
    ax[2].set_title("Top Genres")
    ax[2].set_ylabel("Genre")
    ax[2].set_xlabel("Play count")

    # remove top and right spines
    for i in range(3):
        ax[i].spines['top'].set_visible(False)
        ax[i].spines['right'].set_visible(False)

    plt.tight_layout()

    if save:
        plt.savefig("most_items.png")

    plt.show()


def birthday_song(listen_data, birthday):
    timeline_data = listen_data.copy()
    timeline_data['date_created'] = pd.to_datetime(timeline_data['date_created'])
    timeline_data['date_created'] = timeline_data['date_created'].dt.strftime('%m-%d')
    timeline_data = timeline_data[timeline_data['date_created'] == birthday]

    # group by item ids and then count the play duration to find the most listened song
    song_play_count = timeline_data.groupby('item_id')['play_duration'].sum().reset_index()
    song_play_count.columns = ['item_id', 'play_duration']
    song_play_count = song_play_count.merge(
        timeline_data[['item_id', 'song_name']].drop_duplicates(),
        on='item_id',
        how='left'
    )
    song_play_count = song_play_count[['item_id', 'song_name', 'play_duration']]
    song_play_count = song_play_count.dropna(subset='song_name')

    # print the top song
    print(f"Most listened song on your birthday: {song_play_count['song_name'].iloc[0]}")

birthday_song(listen_data, '06-08')
most_items(best_artists, best_genres, listen_data, save=True)
listen_timeline(listen_data, save=True)
