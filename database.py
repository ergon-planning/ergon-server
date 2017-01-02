import psycopg2
from passlib.context import CryptContext
import random
import string
import datetime

# Global password context
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"]
    )


class Database:
    def __init__(self, database_name, database_user):
        self.database_connection = psycopg2.connect(database=database_name,
                                                    user=database_user)
        self.cursor = self.database_connection.cursor()

    def init_database(self):
        """Creates the table structure in the database.  This is to be used
        once for every database, not on every restart of the program."""
        self.cursor.execute(
            """CREATE TABLE teams
            (id INTEGER PRIMARY KEY,
            name TEXT NOT NULL)""")
        self.cursor.execute(
            """CREATE TABLE users
            (id INTEGER PRIMARY KEY,
            email TEXT UNIQUE,
            password TEXT,
            team_id INTEGER REFERENCES teams(id),
            coach BOOLEAN);""")
        # We use an TIMESTAMP without time zone here, instead of with
        # a timezone, so we assume that the server will be in the same
        # timezone. More info on date types:
        # https://www.postgresql.org/docs/8.0/static/datatype-datetime.html
        self.cursor.execute(
            """CREATE TABLE sessions
            (key TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) NOT NULL,
            exp_date TIMESTAMP NOT NULL);""")
        self.cursor.execute(
            """CREATE TABLE health_data
            (user_id INTEGER REFERENCES users(id) NOT NULL,
            date DATE NOT NULL,
            resting_heart_rate INTEGER NOT NULL,
            weight INTEGER NOT NULL,
            comment TEXT);""")
        self.database_connection.commit()

    def drop_all_tables(self):
        """Drops all tables from the database"""
        self.cursor.execute(
            """DROP TABLE sessions;""")
        self.cursor.execute(
            """DROP TABLE users;""")
        self.cursor.execute(
            """DROP TABLE teams;""")
        self.cursor.execute(
            """DROP TABLE health_data;""")
        self.database_connection.commit()

    def close_database_connection(self):
        """Closes the database_connection and the cursor"""
        self.cursor.close()
        self.database_connection.close()


class UserDoesNotExistError(ValueError):
    def __init__(self, reference_type, value):
        super(UserDoesNotExistError, self).__init__(
            'No user with {}={} exists.'.format(reference_type, value))


class PasswordFieldEmpty(ValueError):
    def __init__(self):
        super(PasswordFieldEmpty, self).__init__(
            'No password submitted')


class ActionNotPermittedError(ValueError):
    def __init__(self, who, what):
        super(ActionNotPermittedError, self).__init__(
            '{} is not permitted to {}'.format(who, what))


class UserDatabase:
    def __init__(self, database):
        self.d = database

    def add_user(self, email, password):
        """Adds an user to the database, using the given email as
        email, the given password as password and a new id, one higher
        than the highest id in the database."""

        # Check if password is not empty
        if password == "":
            raise PasswordFieldEmpty()
        # Check if there isn't already an user with this email address
        self.d.cursor.execute(
            """SELECT email FROM users
            WHERE email = %s;""", (email,))
        if self.d.cursor.fetchone() is not None:
            raise UserDoesNotExistError('email', email)

        # Find the current max_id to generate a new id that is one
        # higher
        self.d.cursor.execute(
            """SELECT MAX(id) FROM users;""")
        (max_id,) = self.d.cursor.fetchone()
        if max_id is None:
            max_id = 0

        # Hash and salt the password using passlib
        password_hash = pwd_context.hash(password)

        self.d.cursor.execute(
            """INSERT INTO users (id, email, password) VALUES
            (%s, %s, %s);""", (max_id + 1, email, password_hash))
        self.d.database_connection.commit()

    def verify_user(self, email, password):
        """Returns whether the given password is the same as the
        password associated with this email address. """
        self.d.cursor.execute(
            """SELECT password FROM users
            WHERE email = %s;""", (email,))

        saved_password_tuple = self.d.cursor.fetchone()
        if saved_password_tuple is None:
            raise UserDoesNotExistError('email', email)
        saved_password_hash = saved_password_tuple[0]

        return pwd_context.verify(password, saved_password_hash)

    def get_user_id(self, email):
        """Returns the user_id associated with this email address"""
        self.d.cursor.execute(
            """SELECT id FROM users
            WHERE email = %s;""", (email,))

        saved_id_tuple = self.d.cursor.fetchone()
        if saved_id_tuple is None:
            raise UserDoesNotExistError('email', email)

        return saved_id_tuple[0]

    def does_user_exist(self, user_id):
        """Checks if an user exists with the given user_id."""
        self.d.cursor.execute(
            """SELECT id FROM users
            WHERE id = %s;""", (user_id,))

        return (self.d.cursor.fetchone() is not None)

    def does_user_email_exist(self, email):
        """Checks if an user exists with the given email."""
        self.d.cursor.execute(
            """SELECT email FROM users
            WHERE email = %s;""", (email,))

        return (self.d.cursor.fetchone() is not None)

    def get_user_team_status(self, user_id):
        """Returns (team_id, coach) of the user with the id user_id,
        be aware that both may be None when the user doesn't have a
        team yet."""
        if not self.does_user_exist(user_id):
            raise UserDoesNotExistError('id', user_id)

        self.d.cursor.execute(
            """SELECT team_id, coach FROM users
            WHERE id = %s;""", (user_id,))
        return self.d.cursor.fetchone()


class TeamDatabase:
    def __init__(self, database):
        self.d = database

    def create_team(self, user_id, team_name):
        """Creates a new team with one member, the user referenced by
        the user_id, this user will automatically be marked as a
        coach.
        Returns the team_id."""
        if not UserDatabase(self.d).does_user_exist(user_id):
            raise UserDoesNotExistError('id', user_id)

        # Find the max team id, so we can choose one that is one
        # higher
        self.d.cursor.execute(
            """SELECT MAX(id) FROM teams;""")
        (max_team_id,) = self.d.cursor.fetchone()
        if max_team_id is None:
            max_team_id = 0
        team_id = max_team_id + 1

        # Create the team
        self.d.cursor.execute(
            """INSERT INTO teams (id, name) VALUES (%s, %s);""",
            (team_id, team_name))

        self.d.cursor.execute(
            """UPDATE users
            SET team_id = %s, coach = %s
            WHERE id = %s;""", (team_id, True, user_id))

        self.d.database_connection.commit()

        return team_id

    def get_team_name(self, team_id):
        """Returns the team name associated with the team_id"""
        self.d.cursor.execute(
            """SELECT name FROM teams
            WHERE id = %s;""", (team_id,))
        team_name_tuple = self.d.cursor.fetchone()
        if team_name_tuple is None:
            raise ValueError(
                """No team found for this team_id""")

        return team_name_tuple[0]

    def add_user_to_team(
            self, adder_id, user_to_add_id, coach=False):
        """Adds an user to the team of the adder (the user who is
        adding another user) with as coach attribute `coach`"""
        udb = UserDatabase(self.d)
        if not udb.does_user_exist(adder_id):
            raise UserDoesNotExistError('id', adder_id)
        if not udb.does_user_exist(user_to_add_id):
            raise UserDoesNotExistError('id', user_to_add_id)

        (team_id, adder_coach) = udb.get_user_team_status(adder_id)
        (user_team_id, _) = udb.get_user_team_status(user_to_add_id)
        if team_id is None:
            raise ValueError('The adder is not in any team')
        if (not adder_coach) or (user_team_id is not None):
            raise ActionNotPermittedError(
                'The user with id={}'.format(adder_id),
                'add the user with id={}'.format(user_to_add_id))

        self.d.cursor.execute(
            """UPDATE users
            SET team_id = %s, coach = %s
            WHERE id = %s;""", (team_id, coach, user_to_add_id))

        self.d.database_connection.commit()

    def remove_user_from_team(
            self, requesting_user_id, user_to_remove_id):
        """Removes a user from the team it is in. Either the
        requesting_user has to be the same as the user_to_remove,
        or the requesting_user has to be a coach in the team of
        the user_to_remove."""
        udb = UserDatabase(self.d)
        if not udb.does_user_exist(requesting_user_id):
            raise UserDoesNotExistError('id', requesting_user_id)
        if not udb.does_user_exist(user_to_remove_id):
            raise UserDoesNotExistError('id', user_to_remove_id)

        (requesting_user_team, requesting_user_coach)\
            = udb.get_user_team_status(requesting_user_id)
        (user_to_remove_team, _) = udb.get_user_team_status(
            user_to_remove_id)

        allowed = (requesting_user_id == user_to_remove_id) or\
                  (requesting_user_team == user_to_remove_team and
                   requesting_user_coach)
        if not allowed:
            raise ActionNotPermittedError(
                'The user with id={}'.format(requesting_user_id),
                'remove this user from this team')

        self.d.cursor.execute(
            """UPDATE users
            SET team_id = %s, coach = %s
            WHERE id = %s""", (None, None, user_to_remove_id))

    def get_team_members(self, team_id):
        """Returns a list of the teammembers associated with the team_id"""
        self.d.cursor.execute(
            """SELECT id, email, coach FROM users
            WHERE team_id = %s;""", (team_id,))
        team_members_list = self.d.cursor.fetchall()
        if not team_members_list:
            raise ValueError(
                """No team found for this team_id""")
        return team_members_list


class SessionDatabase:
    def __init__(self, database):
        self.d = database

    def generate_session_key(self, user_id,
                             livespan=datetime.timedelta(weeks=1)):
        """Generates and returns a new session key for the user, the user
        should already be verified for this. The session key will be
        saved in the sessions table and will be valid for one week.

        This will (as a side effect) remove all session keys that are
        outdated from this user from the session key database."""
        udb = UserDatabase(self.d)
        if not udb.does_user_exist(user_id):
            raise UserDoesNotExistError('id', user_id)

        self.remove_expired_keys(user_id)

        # Generate a random, cryptographically secure string of
        # printable characters, that will be used as session key.
        # Based on http://stackoverflow.com/a/23728630
        session_key_length = 32
        session_key = ''.join(random.SystemRandom()
                              .choice(string.ascii_letters +
                                      string.digits)
                              for _ in range(session_key_length))

        # Set the expiration date of the session key
        expiration_date\
            = datetime.datetime.now() + livespan

        # Inserting the key in the sessions table
        self.d.cursor.execute(
            """INSERT INTO sessions (key, user_id, exp_date)
            VALUES (%s, %s, %s);""", (session_key, user_id,
                                      expiration_date))
        self.d.database_connection.commit()

        return session_key

    def verify_session_key(self, user_id, session_key):
        """Checks whether the session key is correct and valid for the
        user. Returns whether it is."""
        self.d.cursor.execute(
            """SELECT user_id FROM sessions
            WHERE key = %s
            AND exp_date > %s
            AND user_id = %s;""",
            (session_key, datetime.datetime.now(), user_id))

        # fetchone() returns None if no matchin entry is found (ie
        # when the key is invalid).
        return self.d.cursor.fetchone() is not None

    def renew_session_key(self, user_id, session_key,
                          livespan=datetime.timedelta(weeks=1)):
        """Renews the given session key for the user. The key will
        expire one week after calling this function if it isn't
        renewed in the mean time."""
        self.d.cursor.execute(
            """UPDATE sessions
            SET exp_date = %s
            WHERE user_id = %s
            AND key = %s;""",
            (datetime.datetime.now() + livespan,
             user_id, session_key))

        self.d.database_connection.commit()

    def remove_expired_keys(self, user_id):
        """Removes all expired session keys for this user from the
        sessions database."""
        self.d.cursor.execute(
            """DELETE FROM sessions
            WHERE user_id = %s
            AND exp_date < %s;""", (user_id,
                                    datetime.datetime.now()))

        self.d.database_connection.commit()


class HealthDatabase:
    def __init__(self, database):
        self.d = database

    def add_health_data(self, user_id, date, resting_heart_rate,
                        weight, comment):
        """Adds an health_data entry to the health_data table in the
        database. If there already exists an entry for this user on
        the same date, that entry is updated instead.

        `date` should already be an datetime.date object.

        Raises an UserDoesNotExistError if no user exists with the
        user_id."""
        udb = UserDatabase(self.d)
        if not udb.does_user_exist(user_id):
            raise UserDoesNotExistError('id', user_id)

        # get_healt_data returns None if no entry exist
        already_exists = self.get_health_data(user_id, date)\
                         is not None

        if already_exists:
            # Update the current entry
            self.d.cursor.execute(
                """UPDATE health_data
                SET resting_heart_rate = %s,
                weight = %s,
                comment = %s
                WHERE user_id = %s
                AND date = %s;""",
                (resting_heart_rate, weight,
                 comment, user_id, date))
        else:
            # Insert a new entry
            self.d.cursor.execute(
                """INSERT INTO health_data
                (user_id, date, resting_heart_rate, weight, comment)
                VALUES (%s, %s, %s, %s, %s);""",
                (user_id, date, resting_heart_rate, weight, comment))

        self.d.database_connection.commit()

    def get_health_data(self, user_id, date):
        """Returns the (resting_heart_rate, weight, comment) for the given
        date and user_id.
        If no entry is found, it returns None.
        If multiple entries exist, it returns the first one gotten
        with fetchone()."""
        self.d.cursor.execute(
            """SELECT resting_heart_rate, weight, comment FROM health_data
            WHERE user_id = %s
            AND date = %s;""", (user_id, date))
        return self.d.cursor.fetchone()
