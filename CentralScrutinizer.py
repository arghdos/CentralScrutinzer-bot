import DataExtractors
import logging
from logging.handlers import RotatingFileHandler
import Blacklist
import threading
import ScanSub
import BlacklistQuery
import StrikeCounter
import atexit
import sys
import time
import utilitymethods

class CentralScrutinizer(object):
    """
    The main bot object.  Owns / controls / moniters all other threads
    """
    def __init__(self, credentials, policy, database_file, debug = False):
        self.credentials = credentials
        self.policy = policy
        self.database_file = database_file

        #test that praw-multiprocess is started
        test_praw = utilitymethods.create_multiprocess_praw(self.credentials)
        if test_praw is None:
            raise Exception("Cannot connect to praw-multiprocess, ensure it is started and check configuration.")

        Log = logging.getLogger()
        if debug:
            Log.setLevel(logging.DEBUG)
            # create file handler which logs even debug messages
            fh = RotatingFileHandler('error.log')
            fh.setLevel(logging.DEBUG)
            # create console handler with a higher log level
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.ERROR)
            # create formatter and add it to the handlers
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            ch.setFormatter(formatter)
            # add the handlers to the logger
            Log.addHandler(fh)
            Log.addHandler(ch)
        else:
            # create file handler which logs even debug messages
            fh = RotatingFileHandler('error.log')
            fh.setLevel(logging.ERROR)
            # create console handler with a higher log level
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            # add the handlers to the logger
            Log.addHandler(fh)

        # add praw log
        handler = RotatingFileHandler('prmulti.log')
        handler.setLevel(logging.DEBUG)
        logger = logging.getLogger('prawcore')
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        #schedule log closing for exit

        atexit.register(self.close)

        #first try to create all the data extractors
        try:
            youtube = DataExtractors.YoutubeExtractor(credentials['GOOGLEID'], policy)
        except Exception, e:
            logging.critical("Could not create Youtube data extractor!")
            logging.debug(str(e))

        try:
            soundcloud = DataExtractors.SoundCloudExtractor(credentials['SOUNDCLOUDID'], policy)
        except Exception, e:
            logging.critical("Could not create Soundcloud data extractor!")
            logging.debug(str(e))

        try:
            bandcamp = DataExtractors.BandCampExtractor()
        except Exception, e:
            logging.critical("Could not create Bandcamp data extractor!")
            logging.debug(str(e))

        #next create a blacklist object for each
        self.extractors = [bandcamp, youtube, soundcloud]
        self.extractors = [e for e in self.extractors if e]
        self.blacklists = [Blacklist.Blacklist(e, database_file) for e in self.extractors]

        #store policy
        self.policy = policy

        #locking and errors
        self.lock = threading.Lock()
        self.err_count = 0

        self.ss = ScanSub.SubScanner(self)
        self.bquery = BlacklistQuery.BlacklistQuery(self)
        self.scount = StrikeCounter.StrikeCounter(self, recount_strikes=self.policy.force_recount)
        self.mlog = ScanSub.ModLogScanner(self)
        self.h_scan = ScanSub.HistoricalScanner(self)

        self.reddit_threads = [self.ss, self.bquery, self.scount, self.mlog, self.h_scan]

        self.threads = []

    def run(self):
        for thread in self.reddit_threads:
            self.threads.append(threading.Thread(target=thread.run))

        for thread in self.threads:
            thread.start()

        for thread in self.threads:
            thread.join()


    def close(self):
        x = logging._handlers.copy()
        for i in x:
            logging.getLogger().removeHandler(i)
            i.flush()
            i.close()

    def request_pause(self):
        for thread in self.reddit_threads:
            thread.wait.set()

        time.sleep(self.policy.Pause_Period)

        for thread in self.reddit_threads:
            thread.wait.clear()

    @classmethod
    def request_exit(cls):
        #send the shutdown signal
        for thread in cls.reddit_threads:
            thread.exit.set()
