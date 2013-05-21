# TV Shows tracker

I created this web application to follow my favorite shows and track for each one what is the last episode I saw, and when the next will be broadcast. It uses TVRage to retrieve show information and TheTVDB to get show artwork.

It requires Python 2 and Redis (for persistence)

**Attention:** This is currently a work in progress. It is working in its current state but I'm working to make it easier to deploy, but also manage edge cases and properly document the code.

If you have any problems, don't hesitate to contact me on Twitter [@alexandreblin](http://twitter.com/alexandreblin).

## Features

 * Add and track what TV shows you are watching
 * Quickly see which episode you should see next
 * See when the next episode of your favorite show will air
 * Get subtitles for each episode with a quick link to the corresponding Addic7ed.com page
 * RESTful (hopefully) API to access your data using another application (*TODO: document it*)

## Screenshots

[![Overview](http://i.imgur.com/1DcVqYs.png)](http://i.imgur.com/L5lpivO.png) [![Show list](http://i.imgur.com/x9CKojv.png)](http://i.imgur.com/aiwJpql.jpg) [![Show details](http://i.imgur.com/ima1bSb.png)](http://i.imgur.com/4QAClim.png)

## Installation

Clone this repository, then setup a virtual environment:

    git clone https://github.com/alexandreblin/tvshows.git tvshows
    cd tvshows/
    virtualenv .
    . bin/activate

Then proceed to installing the dependencies:

	pip install -r requirements.txt

This will install the following packages:

* Flask
* Flask-Babel
* Flask-Login
* Flask-WTF
* PIL
* lxml
* redis
* requests

Once it's done, just copy config.cfg.sample to config.cfg in tvshows/config and edit it to set the Redis host/port.

You also need an API key from [TheTVDB](http://thetvdb.com/) in order to fetch show posters. Register [here](http://thetvdb.com/?tab=register), then go to your account and add a new application in order to get your API key. Then put it in your config.cfg file.

## Usage

To run the application locally, just do the following:

	python run.py

The application will them be available on `http://localhost:5000`

Any error will be logged to `tvshows/log/error.log`.

You can specify the port and/or bind address:

    python run.py 8080
    python run.py 127.0.0.1 8080

You can also run in debug mode in order to see the errors in your browser and use Werkzeug's debug console :

	DEBUG=1 python run.py

## Deployment with Apache + mod_wsgi

Create a VHost and add the following directives to it:

    WSGIPassAuthorization On

    WSGIDaemonProcess tvshows threads=5
    WSGIScriptAlias / /var/www/tvshows/app.wsgi
    
    Alias /static /var/www/tvshows/tvshows/static
    
    <Directory /var/www/tvshows/>
        WSGIProcessGroup tvshows
    </Directory>

Don't forget to change the path to where you cloned the repository.
