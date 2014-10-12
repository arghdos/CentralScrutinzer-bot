import DataExtractors
import logging
import Blacklist
import threading
import ScanSub
import BlacklistQuery
import StrikeCounter
import atexit
import sys

class CentralScrutinizer(object):
    """
    The main bot object.  Owns / controls / moniters all other threads
    """
    def __init__(self, credentials, policy, database_file, debug = False):
        self.credentials = credentials
        self.policy = policy
        self.database_file = database_file

        Log = logging.getLogger()
        if debug:
            Log.setLevel(logging.DEBUG)
            # create file handler which logs even debug messages
            fh = logging.FileHandler('error.log')
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
            fh = logging.FileHandler('error.log')
            fh.setLevel(logging.ERROR)
            # create console handler with a higher log level
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            # add the handlers to the logger
            Log.addHandler(fh)

        #schedule log closing for exit
        atexit.register(self.close)

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

        #locking and errors
        self.lock = threading.Lock()
        self.err_count = 0

        self.ss = ScanSub.SubScanner(self)
        self.bquery = BlacklistQuery.BlacklistQuery(self)
        self.scount = StrikeCounter.StrikeCounter(self)


    def close(self):
        x = logging._handlers.copy()
        for i in x:
            logging.getLogger().removeHandler(i)
            i.flush()
            i.close()

    def request_pause(self):
        raise NotImplementedError
