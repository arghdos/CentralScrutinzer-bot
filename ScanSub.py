"""
Scans the given sub for any new posts, processing them and checking for blacklist / delete-reposts / etc.
"""

import logging
import datetime
import threading
import Blacklist
from Blacklist import BlacklistEnums
import DataExtractors
import DataBase
import Actions
import utilitymethods
import multiprocessing
import socket

class scan_result:
    FoundOld, DidNotFind, Error = range(3)

class SubScanner(object):
    def __init__(self, owner, credentials, policy, database_file):
        """Creates a new subscanner

        :param owner: our owner! should implement a warn function, so we can warn them when too many errors are encountered
        :param credentials: a dictionary containing the credentials to be used
        :param policy: the policy on blacklist/whitelist etc.  derived from the policy class
        :param database_file: the database file to use
        """

        self.owner = owner
        #first try to create all the data extractors
        try:
            youtube = DataExtractors.YoutubeExtractor(credentials['GOOGLEID'])
        except Exception, e:
            logging.critical("Could not create Youtube data extractor!")
            logging.debug(str(e))

        try:
            soundcloud = DataExtractors.SoundCloudExtractor(credentials['SOUNDCLOUDID'])
        except Exception, e:
            logging.critical("Could not create Youtube data extractor!")
            logging.debug(str(e))

        try:
            bandcamp = DataExtractors.BandCampExtractor()
        except Exception, e:
            logging.critical("Could not create Youtube data extractor!")
            logging.debug(str(e))

        #next create a blacklist object for each
        self.extractors = [youtube, soundcloud, bandcamp]
        self.extractors = [e for e in self.extractors if e]
        self.blacklists = [Blacklist.Blacklist(e, database_file) for e in self.extractors]

        #store policy
        self.policy = policy

        #create a wait/exit condition
        self.wait = threading.Event()
        self.exit = threading.Event()
        self.paused = True
        self.exit = False

        #check for empty database
        self.file = database_file
        scan = False
        with DataBase.DataBaseWrapper(self.file) as db:
            if db.check_reddit_empty() and db.check_channel_empty():
                if policy.Historical_Scan_On_New_Database:
                    scan = True

            #get previous ids
            self.last_seen = "" if db.check_reddit_empty() else db.newest_reddit_entries()


        if scan:
            raise NotImplementedError

        #old posts stored here
        self.cached_posts = []

        #create praw
        self.praw = utilitymethods.create_multiprocess_praw(credentials)
        self.sub = utilitymethods.get_subreddit(credentials, self.praw)

        #err count
        self.errcount = 0

        self.pool = multiprocessing.Pool(processes=policy.Threads)

    def __check_cached(self, id):
        return any(i == id for i in self.cached_posts)

    def __get_blacklist(self, url):
        for b in self.blacklists:
            if b.check_domain(url):
                return b

    def scan(self, limit=10):
        """Scans the sub.

        :param limit: If None, the limit in the policy will be used
        :return: True if self.last_seen was reached, False otherwise
        """

        lim = limit if limit else self.policy.Posts_To_Load
        #first ask for posts
        posts = Actions.get_posts(self.sub, lim)
        found_old = False
        added_posts = []

        try:
            post_data = [(post.id, post.url, post) for post in posts]
        except socket.error, e:
            if e.errno == 10061:
                logging.critical("praw-multiprocess not started!")
            else:
                logging.error(str(e))
            return scan_result.Error
        #get list of resolved urls
        urls = self.pool.map(Actions.resolve_url, [post[1] for post in post_data])
        #get list we need to process
        for i, url in enumerate(urls):
            #if we've reached the last one, break
            if post_data[i][0] == self.last_seen:
                found_old = True
                break

            #don't look at old ones again
            if self.__check_cached(post_data[i][0]):
                continue
            self.cached_posts.append(post_data[i][0])

            deleted = False
            #check black/whitelist
            blacklist = self.__get_blacklist(url)
            channel_id, channel_url = blacklist.data.channel_id(url)
            check = blacklist.check_blacklist(id=channel_id)
            if check == BlacklistEnums.Blacklisted:
                self.policy.on_blacklist(post_data[i][2])
                continue
            if check == BlacklistEnums.Whitelisted:
                self.policy.on_whitelist(post_data[i][2])
            #if whitelisted or not found, store reddit_record
            added_posts.append((post_data[i][0], channel_id, blacklist.domains[0], datetime.datetime.now()))

        #finally add our new posts to the reddit_record
        with DataBase.DataBaseWrapper(self.file, False) as db:
            db.add_reddit(added_posts)

        if found_old:
            return scan_result.FoundOld
        else:
            return scan_result.DidNotFind

    def __shutdown(self):
        pass

    def run(self):
        while True:
            #check for pause
            while self.wait.is_set():
                self.wait.wait(self.policy.Pause_Period)
            #check for exit
            if self.exit.is_set():
                self.__shutdown()
                break

            #scan, until old id found
            result = self.scan()
            if result == scan_result.DidNotFind:
                retry_count = 0
                while not reached_old and retry_count < self.policy.Max_Retries:
                    reached_old = self.scan(self.policy.Posts_To_Load * (retry_count + 1) * self.policy.Retry_Multiplier)
                    retry_count += 1
                if retry_count == 5:
                    logging.warning("Old post with id: " + self.last_seen + " not found!")
            elif result == scan_result.Error:
                self.errcount += 1

            if self.errcount >= self.policy.Max_Err_Count:
                self.owner.warn()

            #update old id
            with DataBase.DataBaseWrapper(self.file) as db:
                #get previous id
                self.last_seen = db.newest_reddit_entries()

            #and wait
            threading.current_thread.wait(self.policy.Scan_Sub_Period)
