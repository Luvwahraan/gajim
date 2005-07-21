## logger.py
##
## Gajim Team:
## - Yann Le Boulanger <asterix@lagaule.org>
## - Vincent Hanquez <tab@snarc.org>
## - Nikos Kouremenos <kourem@gmail.com>
##
##      Copyright (C) 2003-2005 Gajim Team
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published
## by the Free Software Foundation; version 2 only.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##

import os
import sys
import time
import common.gajim
from common import i18n
_ = i18n._
from common import helpers

LOGPATH = os.path.expanduser('~/.gajim/logs')
if os.name == 'nt':
	try:
		# Documents and Settings\[User Name]\Application Data\Gajim\logs
		LOGPATH = os.environ['appdata'] + '/Gajim/Logs'
	except KeyError:
		# win9x, ./logs
		LOGPATH = 'Logs'

class Logger:
	def __init__(self):
		dot_gajim = os.path.dirname(LOGPATH)
		if os.path.isfile(dot_gajim):
			print dot_gajim, 'is file but it should be a directory'
			print 'Gajim will now exit'
			sys.exit()
		if os.path.isdir(dot_gajim):
			if os.path.isfile(LOGPATH):
				print LOGPATH, 'is file but it should be a directory'
				print 'Gajim will now exit'
				sys.exit()
		else: # dot_gajim doesn't exist
			if dot_gajim: # is '' on win9x so avoid that
				print 'creating', dot_gajim , 'directory'
				os.mkdir(dot_gajim)
			if not os.path.isdir(LOGPATH):
				print 'creating', LOGPATH, 'directory'
				os.mkdir(LOGPATH)

	def write(self, kind, msg, jid, show = None, tim = None):
		if not tim:
			tim = time.time()
		else:
			tim = time.mktime(tim)

		if not msg:
			msg = ''

		msg = helpers.to_one_line(msg)
		if len(jid.split('/')) > 1:
			ji, nick = jid.split('/', 1)
		else:
			ji = jid
			nick = ''
		files = []
		if kind == 'status': #we save time:jid:show:msg
			if not show:
				show = 'online'
			if common.gajim.config.get('log_notif_in_user_file'):
				path_to_file = os.path.join(LOGPATH, ji)
				if os.path.isdir(path_to_file):
					jid = 'gcstatus'
					msg = show + ':' + msg
					show = nick
					files.append(ji + '/' + ji)
					if os.path.isfile(jid):
						files.append(jid)
				else:
					files.append(ji)
			if common.gajim.config.get('log_notif_in_sep_file'):
				files.append('notify.log')
		elif kind == 'incoming': # we save time:recv:message
			path_to_file = os.path.join(LOGPATH, ji)
			if os.path.isdir(path_to_file):
				files.append(jid)
			else:
				files.append(ji)
			jid = 'recv'
			show = msg
			msg = ''
		elif kind == 'outgoing': # we save time:sent:message
			path_to_file = os.path.join(LOGPATH, ji)
			if os.path.isdir(path_to_file):
				files.append(jid)
			else:
				files.append(ji)
			jid = 'sent'
			show = msg
			msg = ''
		elif kind == 'gc': # we save time:gc:nick:message
			# create the folder if needed
			ji_fn = os.path.join(LOGPATH, ji)
			if os.path.isfile(ji_fn):
				os.remove(ji_fn)
			if not os.path.isdir(ji_fn):
				os.mkdir(ji_fn)
			files.append(ji + '/' + ji)
			jid = 'gc'
			show = nick
		for f in files:
			path_to_file = os.path.join(LOGPATH, f)
			fic = open(path_to_file, 'a')
			fic.write('%s:%s:%s' % (tim, jid, show))
			if msg:
				fic.write(':' + msg)
			fic.write('\n')
			fic.close()

	def __get_path_to_file(self, fjid):
		jid = fjid.split('/')[0]
		path_to_file = os.path.join(LOGPATH, jid)
		if os.path.isdir(path_to_file):
			if fjid == jid: # we want to read the gc history
				path_to_file = os.path.join(LOGPATH, jid + '/' + jid)
			else: #we want to read pm history
				path_to_file = os.path.join(LOGPATH, fjid)
		return path_to_file

	def get_nb_line(self, fjid):
		'''return total number of lines in a log file
		return 0 if log file does not exist'''
		path_to_file = self.__get_path_to_file(fjid)
		if not os.path.exists(path_to_file):
			return 0
		fic = open(path_to_file, 'r')
		nb = 0 # number of lines
		while fic.readline():
			nb += 1
		fic.close()
		return nb

	def read(self, fjid, begin_line, end_line):
		'''return number of lines read and the text in the lines
		return 0 and empty respectively if log file does not exist'''
		path_to_file = self.__get_path_to_file(fjid)
		if not os.path.exists(path_to_file):
			return 0, []
		fic = open(path_to_file, 'r')
		nb = 0 # number of lines
		lines = []
		while (nb < begin_line and fic.readline()):
			nb += 1
		while nb < end_line:
			line = fic.readline()
			if line:
				line = helpers.from_one_line(line)
				lineSplited = line.split(':')
				if len(lineSplited) > 2:
					lines.append(lineSplited)
			nb += 1
		return nb, lines
