import random
import time

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import logger
import model


class SmartClient(object):
    engines = []
    log = logger.get_logger(__file__)
    last_shuffle = 0

    @staticmethod
    def parse_db_uri(db_uri):
        if "cockroachdb://" in db_uri and db_uri.count(",") > 1:
            return _MultipleEndpoints
        return _SingleEndpoint

    def __new__(cls, db_uri):
        o = object.__new__(cls.parse_db_uri(db_uri))
        return o

    def __init__(self, db_uri):
        self._create_engines(db_uri.split(","))

    def _create_engines(self, uri_list):
        for single_uri in uri_list:
            e = create_engine(single_uri)
            if e.url not in [k.url for k in self.engines]:
                self.log.info("%s %s" % (e.driver, e.url))
                self.engines.append(e)
        self.log.info("total: %d" % len(self.engines))

    def create_conn_with_session(self):
        conn = self.get_engine_connection()
        Session = sessionmaker(bind=conn)
        session = Session(bind=conn)
        return conn, session

    def get_engine_connection(self):
        ts = time.time()
        if time.time() - self.last_shuffle > 60:
            random.shuffle(self.engines)
            self.last_shuffle = ts
        for engine in self.engines:
            try:
                conn = engine.connect()
                return conn
            except OperationalError:
                self.log.error("could not connect to %s" % engine.url)
        raise ConnectionError(",".join(["%s" % k.url for k in self.engines]))

    def create_base(self):
        model.Base.metadata.create_all(self.get_engine_connection())


class _SingleEndpoint(SmartClient):
    pass


class _MultipleEndpoints(SmartClient):
    pass