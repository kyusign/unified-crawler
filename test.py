from pytube import YouTube, Search

# https://github.com/pytube/pytube
# https://github.com/pytube/pytube/issues/2069
video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

yt = YouTube(video_url)
print(yt.title)