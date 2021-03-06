[![Build Status](https://travis-ci.org/rlmv/doc-trips.svg?branch=master)](https://travis-ci.org/rlmv/doc-trips)
[![Coverage Status](https://coveralls.io/repos/github/rlmv/doc-trips/badge.svg?branch=master)](https://coveralls.io/github/rlmv/doc-trips?branch=master)
[![Updates](https://pyup.io/repos/github/rlmv/doc-trips/shield.svg)](https://pyup.io/repos/github/rlmv/doc-trips/)

# DOC First-Year Trips Database

## Installation

To get a local development version running, install [Python 3.6](https://www.python.org/downloads/)
and [Git](https://git-scm.com/book/id/v2/Getting-Started-Installing-Git). Run
the following to install the project:

    git clone https://github.com/rlmv/doc-trips.git
    cd doc-trips
    make install

This will set up a virtual environment and install all Python
dependencies. Many `Makefile` commands use the Python executable installed in
the virtual environment; however, to use the virtual environment for other
management commands you will need to run

    source venv/bin/activate

each time you begin development.

## Database

The site uses PostgreSQL as a database backend in production. The project is
set up to run a local Postgres instance using Docker. You can install Docker
[here](https://docs.docker.com/install/). Once that is done, run the following
to ensure everything is properly set up:

    make postgres

Then run the following from the command line:

    make reset_db
    make migrate
    make bootstrap

This will create a database user, run all the database migrations, and load the
minimal set of data required to use the database.

## Environment Variables

The `settings` module reads required configuration values from the environment.
During local development, it also reads values from a local `config.yml` file
which was created when you ran `make install`.  This file is never checked into
the repository so you can use it to store API keys for development. It contains
some required Django configuration values:

    DEBUG: "True"
    SECRET_KEY: "some secret key"
    DATABASE_URL: "postgres://fytuser:password@localhost/fyt"

To use the Google Maps integration for the `transport` app,
get API keys for the [Google Maps Directions API](https://developers.google.com/maps/documentation/directions/)
and the [Google Maps Embed API](https://developers.google.com/maps/documentation/embed/)
and add them to `config.yml`:

    GOOGLE_MAPS_KEY: "your google maps key"
    GOOGLE_MAPS_BROWSER_KEY: "your google maps browser key"

Note that `GOOGLE_MAPS_BROWSER_KEY` is used browser-side. Be sure to set
referrer restrictions on it!

In 2015 and 2016, Leader and Croo applications were submitted with an attached
word document. Those files were uploaded to Amazon S3. The application was
refactored in 2017 to use form-based questions, but those files are still in the
database. To use this code you need to set up an Amazon S3 bucket and am IAM
user with AmazonS3FullAccess permission, and add these keys to `config.yml`:

    AWS_ACCESS_KEY_ID: "your key id"
    AWS_SECRET_ACCESS_KEY: "your secret key"
    AWS_STORAGE_BUCKET_NAME: "a bucket name"

## Development Server

To start the Django development server, run

    make

and visit [localhost:8000](localhost:8000). Once you have logged in via
Dartmouth WebAuth, run

    ./manage.py setsuperuser <netid>

with your NetId to give yourself superuser priveleges.

## Testing

Run the test suite with

    make test

Calls to external APIs (Dartmouth, Amazon S3, Google Maps) are mocked out using
[VCRpy](https://vcrpy.readthedocs.io) so the tests can be run without
configuring credentials for those services.

## Deployment & CI

The application runs on Heroku, and there is a deployment pipeline in
place. All commits pushed to the `master` branch on Github are tested with
TravisCI and, if the tests succeed, are deployed directly to Heroku.  Database
migrations are run automatically in the release stage; if a migration fails the
release is not deployed.

You will need to install the
[Heroku Toolbelt](https://devcenter.heroku.com/articles/heroku-command).

I highly recommend setting up a
[Heroku staging instance](https://devcenter.heroku.com/articles/multiple-environments)
for testing and experimentation.

The production site uses [Sentry](https://sentry.io) for error tracking and alerts.

## Dartmouth Services

All logins to the database are done via [Dartmouth
WebAuth](http://tech.dartmouth.edu/its/services-support/help-yourself/knowledge-base/web-auth-frequently-asked-questions)
which uses the CAS protocol. None of the existing CAS clients for Django worked
for me (either no Python 3 support or missing features) so a stripped down and
modified version of one (I believe
[kstateome/django-cas](https://github.com/kstateome/django-cas)) can be found
in `fyt.webauth`. The `DartmouthUser` model stores information parsed from the
CAS responses.

Since CAS responses do not contain the user's email, this is retreived from
http://dndprofiles.dartmouth.edu. There does not seem to be a canonical way to
lookup Dartmouth emails. Dartmouth IT suggests scraping results from
http://lookupdnd.dartmouth.edu/lite if the current system ever fails.

Unfortunately the DND does not contain alumni information and we cannot
programatically find their emails. Therefore when alums log in (e.g. to acces
the Raid Blog) they must update their email manually.

## The ever-present `trips_year` variable

There is one `TripsYear` object for each year of the the trips program.
Every other model in the database (except for `User` and a few configuration
singletons) references this master model via a `ForeignKey` inherited from
`DatabaseModel`. We end up passing around `trips_year` values a lot.

All views which have a `trips_year` url keyword argument should inherit from
the `TripsYearMixin` class-based view. This view pulls the `trips_year` from
url kwargs, filters querysets, automatically restricts related objects choices
in forms to those of the same `trips_year`, and adds the `trips_year` of the
view to the template context.

Objects for any `trips_year` may only relate (via ForeignKey, etc.) to objects
of the same `trips_year`. However, this is not enforced at the database level
so custom forms needs to filter `field.queryset`. `TripsYearMixin` takes care
of this by default (see but you need to be careful when using explicit
`form_class` values in class-based views.

### Migrating to the next `trips_year`

The `db.forward` module is responsible for migrating the database to the next
`trips_year`. It copies all data stored in persisted objects
(e.g. `TripTemplates`, `Campsites`, `Routes`) to a new instance for the next
year, and deletes all sensitive personal information. This is not reversible
and should only be done when Trips has completely finished for the year!
