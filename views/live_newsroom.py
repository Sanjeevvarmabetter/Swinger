"""Live Newsroom — official live streams of business and world news channels (YouTube embeds)."""
from __future__ import annotations

import html
import json
import re

import streamlit as st

from tradingos.config import PROJECT_ROOT
from tradingos.ui import components as ui

ui.render_top_bar(show_refresh=False)
ui.page_header("Live Newsroom", "Official live streams from business and world news channels. Streams are embedded "
                                "from each channel's own YouTube account; availability depends on the broadcaster.")


@st.cache_data(show_spinner=False)
def _channels() -> list[dict]:
    data = json.loads((PROJECT_ROOT / "config" / "live_channels.json").read_text())["channels"]
    return [c for c in data if re.fullmatch(r"UC[\w-]{22}", c.get("channel_id", ""))]


chans = _channels()
if not chans:
    ui.empty_state("No channels configured in config/live_channels.json.")
    st.stop()

regions = ["All"] + sorted({c["region"] for c in chans})
region = st.segmented_control("Region", regions, default="All", key="live_region", label_visibility="collapsed") or "All"
shown = [c for c in chans if region == "All" or c["region"] == region]
names = [c["name"] for c in shown]
default = st.session_state.get("live_pick") if st.session_state.get("live_pick") in names else names[0]
pick = st.selectbox("Channel", names, index=names.index(default), key="live_pick")
ch = next(c for c in shown if c["name"] == pick)

cid = ch["channel_id"]
embed = f"https://www.youtube-nocookie.com/embed/live_stream?channel={cid}&autoplay=0&rel=0"
st.markdown(
    f'<div class="video-wrap"><iframe src="{html.escape(embed, quote=True)}" title="{html.escape(ch["name"])} live stream" '
    f'allow="encrypted-media; picture-in-picture; fullscreen" allowfullscreen loading="lazy" '
    f'referrerpolicy="strict-origin-when-cross-origin"></iframe></div>',
    unsafe_allow_html=True)
with st.container(horizontal=True, gap="small", vertical_alignment="center"):
    st.link_button("Open live on YouTube", f"https://www.youtube.com/channel/{cid}/live", icon=":material/open_in_new:")
    st.link_button("Channel videos", f"https://www.youtube.com/channel/{cid}/videos", icon=":material/video_library:")
st.caption("If the player says the video is unavailable, the channel is not live right now or does not allow "
           "embedding — use “Open live on YouTube”. This page does not record, transcribe or summarise streams.")

st.markdown('<div class="sec-title">All channels</div>', unsafe_allow_html=True)
rows = "".join(
    f'<div class="story"><div class="story-head">{html.escape(c["name"])}</div>'
    f'<div class="story-meta">{html.escape(c["region"])} · '
    f'<a href="https://www.youtube.com/channel/{c["channel_id"]}/live" target="_blank" rel="noopener noreferrer">'
    f'Watch live ↗</a></div></div>' for c in shown)
st.markdown(f'<div class="tile-grid">{rows}</div>', unsafe_allow_html=True)
