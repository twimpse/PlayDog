#
# Regular cron jobs for the playdog package.
#
0 4	* * *	root	[ -x /usr/bin/playdog_maintenance ] && /usr/bin/playdog_maintenance
