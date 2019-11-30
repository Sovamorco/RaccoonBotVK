from credentials import anilist_token, vkPersUserID
import httpx
from utils import vkMsg
from time import time, mktime
import feedparser as fp
import re
from datetime import datetime
import asyncio

q = []


async def graphql_request(query):
    url = 'https://graphql.anilist.co'
    headers = {
        'Authorization': 'Bearer '+anilist_token
    }
    data = {
        'query': query
    }
    async with httpx.AsyncClient() as client:
        res = await client.post(url, headers=headers, data=data)
        res = res.json()
    return res


async def get_notifications(count):
    query = 'query{Page(perPage: '+str(count)+') {notifications(type_in: [AIRING, ACTIVITY_MESSAGE, ACTIVITY_REPLY, FOLLOWING, ACTIVITY_MENTION, THREAD_COMMENT_MENTION, THREAD_SUBSCRIBED, THREAD_COMMENT_REPLY, ACTIVITY_LIKE, ACTIVITY_REPLY_LIKE, THREAD_LIKE, THREAD_COMMENT_LIKE, ACTIVITY_REPLY_SUBSCRIBED, RELATED_MEDIA_ADDITION], resetNotificationCount: true) {... on AiringNotification {type,episode,media {id,type,title {userPreferred}}}... on RelatedMediaAdditionNotification {type,media {id,type,title {userPreferred},siteUrl}}... on FollowingNotification {type}... on ActivityMessageNotification {type}... on ActivityMentionNotification {type}... on ActivityReplyNotification {type}... on ActivityReplySubscribedNotification {type}... on ActivityLikeNotification {type}... on ActivityReplyLikeNotification {type}... on ThreadCommentMentionNotification {type}... on ThreadCommentReplyNotification {type}... on ThreadCommentSubscribedNotification {type}... on ThreadCommentLikeNotification {type}... on ThreadLikeNotification {type}}}}'
    res = await graphql_request(query)
    return res['data']['Page']['notifications']


async def update_notifications():
    query = '{Viewer{unreadNotificationCount}}'
    ncnt = await graphql_request(query)
    ncnt = ncnt['data']['Viewer']['unreadNotificationCount']
    if ncnt != 0:
        notifs = get_notifications(ncnt)
        for notif in notifs:
            if notif['type'] == 'AIRING':
                q.append(notif['media']['title']['userPreferred'])
                yield f'Вышла {notif["episode"]} серия {notif["media"]["title"]["userPreferred"]}'
            elif notif['type'] == 'RELATED_MEDIA_ADDITION':
                s = 'На сайт добавлено новое аниме: {}\n{}' if notif['media']['type'] == 'ANIME' else 'На сайт добавлена новая манга/новелла: {}\n{}'
                yield s.format(notif['media']['title']['userPreferred'], notif['media']['siteUrl'].replace('\/', '/'))


async def search_anilist(title):
    query = 'query{anime:Page(perPage: 20){results: media(type: ANIME, isAdult: false, search: "'+title+'"){title {userPreferred},nextAiringEpisode{episode},status, endDate{year,month,day}}}}'
    res = await graphql_request(query)
    res = res['data']['anime']['results']
    if res:
        for anime in res:
            if anime['status'] == 'RELEASING':
                if anime['nextAiringEpisode']:
                    return anime['title']['userPreferred'], anime['nextAiringEpisode']['episode']
                return anime['title']['userPreferred'], 0
            else:
                if anime['endDate'] and anime['endDate']['day']:
                    date = anime['endDate']
                    dt = datetime(year=date['year'], month=date['month'], day=date['day'])
                    diff = datetime.today()-dt
                    if diff.days < 10:
                        if anime['nextAiringEpisode']:
                            return anime['title']['userPreferred'], anime['nextAiringEpisode']['episode']
                        return anime['title']['userPreferred'], 0
    return None


def scrape(title):
    group = 'HorribleSubs' if '[HorribleSubs]' in title else 'Erai-raws'
    res = re.sub(r'\[([^)]+?)]', '', title.replace('.mkv', ''))
    ep = re.search(r' [–|-] [0-9]+', res).group()
    res = res.replace(ep, '').strip()
    ep = re.search(r'[0-9]+', ep).group()
    return res, int(ep), group


async def update_rss():
    while True:
        try:
            async with httpx.AsyncClient() as client:
                hsubs = await client.get('http://www.horriblesubs.info/rss.php?res=1080')
                esubs = await client.get('https://ru.erai-raws.info/rss-1080/')
            hsubs = fp.parse(hsubs.text)['entries']
            esubs = fp.parse(esubs.text)['entries']
            for sub in hsubs+esubs:
                dt = sub['published_parsed']
                if time() - mktime(dt) < 30000:
                    scraped = scrape(sub['title'])
                    info = await search_anilist(scraped[0])
                    for _ in range(len(q)):
                        title = q.pop(0)
                        if info[0] == title:
                            await vkMsg(vkPersUserID, f'{scraped[1]} серия {title} вышла в субтитрах от {scraped[2]}!')
                        else:
                            q.append(title)
        finally:
            await asyncio.sleep(60)


async def al_check():
    while True:
        try:
            notifs = update_notifications()
            if notifs:
                async for notif in notifs:
                    await vkMsg(vkPersUserID, notif)
        finally:
            await asyncio.sleep(60)
