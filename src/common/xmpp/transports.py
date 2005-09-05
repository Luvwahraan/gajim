##   transports.py
##
##   Copyright (C) 2003-2004 Alexey "Snake" Nezhdanov
##
##   This program is free software; you can redistribute it and/or modify
##   it under the terms of the GNU General Public License as published by
##   the Free Software Foundation; either version 2, or (at your option)
##   any later version.
##
##   This program is distributed in the hope that it will be useful,
##   but WITHOUT ANY WARRANTY; without even the implied warranty of
##   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##   GNU General Public License for more details.

# $Id: transports.py,v 1.20 2005/05/12 07:35:55 snakeru Exp $

"""
This module contains the low-level implementations of xmpppy connect methods or
(in other words) transports for xmpp-stanzas.
Currently here is three transports:
direct TCP connect - TCPsocket class
proxied TCP connect - HTTPPROXYsocket class (CONNECT proxies)
TLS connection - TLS class. Can be used for SSL connections also.

Transports are stackable so you - f.e. TLS use HTPPROXYsocket or TCPsocket as more low-level transport.

Also exception 'error' is defined to allow capture of this module specific exceptions.
"""

import socket,select,base64,dispatcher
from simplexml import ustr
from client import PlugIn
from protocol import *

# determine which DNS resolution library is available
HAVE_DNSPYTHON = False
HAVE_PYDNS = False
try:
    import dns.resolver # http://dnspython.org/
    HAVE_DNSPYTHON = True
except ImportError:
    try:
        import DNS # http://pydns.sf.net/
        HAVE_PYDNS = True
    except ImportError:
	     #TODO: use self.DEBUG()
        print "Couldn't load a supported DNS library. SRV records will not be queried and some servers may not be accessible."

DATA_RECEIVED='DATA RECEIVED'
DATA_SENT='DATA SENT'

class error:
    """An exception to be raised in case of low-level errors in methods of 'transports' module."""
    def __init__(self,comment):
        """Cache the descriptive string"""
        self._comment=comment

    def __str__(self):
        """Serialise exception into pre-cached descriptive string."""
        return self._comment

class TCPsocket(PlugIn):
    """ This class defines direct TCP connection method. """
    def __init__(self, server=None):
        """ Cache connection point 'server'. 'server' is the tuple of (host, port)
            absolutely the same as standart tcp socket uses. """
        PlugIn.__init__(self)
        self.DBG_LINE='socket'
        self._exported_methods=[self.send,self.disconnect]

        # SRV resolver
        if HAVE_DNSPYTHON or HAVE_PYDNS:
            host, port = server
            possible_queries = ['_xmpp-client._tcp.' + host]

            for query in possible_queries:
                try:
                    if HAVE_DNSPYTHON:
                        answers = [x for x in dns.resolver.query(query, 'SRV')]
                        if answers:
                            host = str (answers[0].target)
                            port = int (answers[0].port)
                            break
                    elif HAVE_PYDNS:
                        DNS.ParseResolvConf() # ensure we haven't cached an old configuration
                        response = DNS.Request().req(query, qtype='SRV')
                        answers = response.answers
                        if len(answers) > 0:
                            _, _, port, host = answers[0]['data'] # ignore the priority and weight for now
                            port = int(port)
                            break
                except:
	                 #TODO: use self.DEBUG()
                    print 'An error occurred looking up %s' % query
            server = (host, port)
        # end of SRV resolver

        self._server = server

    def plugin(self, owner):
        """ Fire up connection. Return non-empty string on success.
            Also registers self.disconnected method in the owner's dispatcher.
            Called internally. """
        if not self._server: self._server=(self._owner.Server,5222)
        if not self.connect(self._server): return
        self._owner.Connection=self
        self._owner.RegisterDisconnectHandler(self.disconnected)
        return 'ok'

    def getHost(self):
        """ Return the 'host' value that is connection is [will be] made to."""
        return self._server[0]
    def getPort(self):
        """ Return the 'port' value that is connection is [will be] made to."""
        return self._server[1]

    def connect(self,server=None):
        """ Try to connect. Returns non-empty string on success. """
        try:
            if not server: server=self._server
            self._sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.connect(server)
            self._send=self._sock.sendall
            self._recv=self._sock.recv
            self.DEBUG("Successfully connected to remote host %s"%`server`,'start')
            return 'ok'
        except: pass

    def plugout(self):
        """ Disconnect from the remote server and unregister self.disconnected method from
            the owner's dispatcher. """
        self._owner.DeregisterDisconnectHandler(self.disconnected)
        self.shutdown()
        del self._owner.Connection

    def receive(self):
        """ Reads all pending incoming data. Calls owner's disconnected() method if appropriate."""
        try: received = self._recv(1024000)
        except: received = ''

        while select.select([self._sock],[],[],0)[0]:
            try: add = self._recv(1024000)
            except: add=''
            received +=add
            if not add: break

        if len(received): # length of 0 means disconnect
            self.DEBUG(received,'got')
            if hasattr(self._owner, 'Dispatcher'):
                self._owner.Dispatcher.Event('', DATA_RECEIVED, received)
        else:
            self.DEBUG('Socket error while receiving data','error')
            self._owner.disconnected()
        return received

    def send(self,raw_data):
        """ Writes raw outgoing data. Blocks until done.
            If supplied data is unicode string, encodes it to utf-8 before send."""
        if type(raw_data)==type(u''): raw_data = raw_data.encode('utf-8')
        elif type(raw_data)<>type(''): raw_data = ustr(raw_data).encode('utf-8')
        try:
            self._send(raw_data)
            # Avoid printing messages that are empty keepalive packets.
            if raw_data.strip():
                self.DEBUG(raw_data,'sent')
                self._owner.Dispatcher.Event('', DATA_SENT, raw_data)
        except:
            self.DEBUG("Socket error while sending data",'error')
            self._owner.disconnected()

    def pending_data(self,timeout=0):
        """ Returns true if there is a data ready to be read. """
        return select.select([self._sock],[],[],timeout)[0]

    def disconnect(self):
        """ Closes the socket. """
        self.DEBUG("Closing socket",'stop')
        self._sock.close()

    def disconnected(self):
        """ Called when a Network Error or disconnection occurs.
            Designed to be overidden. """
        self.DEBUG("Socket operation failed",'error')

DBG_CONNECT_PROXY='CONNECTproxy'
class HTTPPROXYsocket(TCPsocket):
    """ HTTP (CONNECT) proxy connection class. Uses TCPsocket as the base class
        redefines only connect method. Allows to use HTTP proxies like squid with
        (optionally) simple authentication (using login and password). """
    def __init__(self,proxy,server):
        """ Caches proxy and target addresses.
            'proxy' argument is a dictionary with mandatory keys 'host' and 'port' (proxy address)
            and optional keys 'user' and 'password' to use for authentication.
            'server' argument is a tuple of host and port - just like TCPsocket uses. """
        TCPsocket.__init__(self,server)
        self.DBG_LINE=DBG_CONNECT_PROXY
        self._proxy=proxy

    def plugin(self, owner):
        """ Starts connection. Used interally. Returns non-empty string on success."""
        owner.debug_flags.append(DBG_CONNECT_PROXY)
        return TCPsocket.plugin(self,owner)

    def connect(self,dupe=None):
        """ Starts connection. Connects to proxy, supplies login and password to it
            (if were specified while creating instance). Instructs proxy to make
            connection to the target server. Returns non-empty sting on success. """
        if not TCPsocket.connect(self,(self._proxy['host'],self._proxy['port'])): return
        self.DEBUG("Proxy server contacted, performing authentification",'start')
        connector = ['CONNECT %s:%s HTTP/1.0'%self._server,
            'Proxy-Connection: Keep-Alive',
            'Pragma: no-cache',
            'Host: %s:%s'%self._server,
            'User-Agent: HTTPPROXYsocket/v0.1']
        if self._proxy.has_key('user') and self._proxy.has_key('password'):
            credentials = '%s:%s'%(self._proxy['user'],self._proxy['password'])
            credentials = base64.encodestring(credentials).strip()
            connector.append('Proxy-Authorization: Basic '+credentials)
        connector.append('\r\n')
        self.send('\r\n'.join(connector))
        reply = self.receive().replace('\r','')
        try: proto,code,desc=reply.split('\n')[0].split(' ',2)
        except: raise error('Invalid proxy reply')
        if code<>'200':
            self.DEBUG('Invalid proxy reply: %s %s %s'%(proto,code,desc),'error')
            self._owner.disconnected()
            return
        while reply.find('\n\n') == -1: reply += self.receive().replace('\r','')
        self.DEBUG("Authentification successfull. Jabber server contacted.",'ok')
        return 'ok'

    def DEBUG(self,text,severity):
        """Overwrites DEBUG tag to allow debug output be presented as "CONNECTproxy"."""
        return self._owner.DEBUG(DBG_CONNECT_PROXY,text,severity)

class TLS(PlugIn):
    """ TLS connection used to encrypts already estabilished tcp connection."""
    def PlugIn(self,owner,now=0):
        """ If the 'now' argument is true then starts using encryption immidiatedly.
            If 'now' in false then starts encryption as soon as TLS feature is
            declared by the server (if it were already declared - it is ok).
        """
        if owner.__dict__.has_key('TLS'): return  # Already enabled.
        PlugIn.PlugIn(self,owner)
        DBG_LINE='TLS'
        if now: return self._startSSL()
        if self._owner.Dispatcher.Stream.features:
            try: self.FeaturesHandler(self._owner.Dispatcher,self._owner.Dispatcher.Stream.features)
            except NodeProcessed: pass
        else: self._owner.RegisterHandlerOnce('features',self.FeaturesHandler,xmlns=NS_STREAMS)
        self.starttls=None

    def plugout(self,now=0):
        """ Unregisters TLS handler's from owner's dispatcher. Take note that encription
            can not be stopped once started. You can only break the connection and start over."""
        self._owner.UnregisterHandler('features',self.FeaturesHandler,xmlns=NS_STREAMS)
#        self._owner.UnregisterHandlerOnce('proceed',self.StartTLSHandler,xmlns=NS_TLS)
#        self._owner.UnregisterHandlerOnce('failure',self.StartTLSHandler,xmlns=NS_TLS)

    def FeaturesHandler(self, conn, feats):
        """ Used to analyse server <features/> tag for TLS support.
            If TLS is supported starts the encryption negotiation. Used internally"""
        if not feats.getTag('starttls',namespace=NS_TLS):
            self.DEBUG("TLS unsupported by remote server.",'warn')
            return
        self.DEBUG("TLS supported by remote server. Requesting TLS start.",'ok')
        self._owner.RegisterHandlerOnce('proceed',self.StartTLSHandler,xmlns=NS_TLS)
        self._owner.RegisterHandlerOnce('failure',self.StartTLSHandler,xmlns=NS_TLS)
        self._owner.Connection.send('<starttls xmlns="%s"/>'%NS_TLS)
        raise NodeProcessed

    def _startSSL(self):
        """ Immidiatedly switch socket to TLS mode. Used internally."""
        tcpsock=self._owner.Connection
        tcpsock._sslObj    = socket.ssl(tcpsock._sock, None, None)
        tcpsock._sslIssuer = tcpsock._sslObj.issuer()
        tcpsock._sslServer = tcpsock._sslObj.server()
        tcpsock._recv = tcpsock._sslObj.read
        tcpsock._send = tcpsock._sslObj.write
        self.starttls='success'

    def StartTLSHandler(self, conn, starttls):
        """ Handle server reply if TLS is allowed to process. Behaves accordingly.
            Used internally."""
        if starttls.getNamespace()<>NS_TLS: return
        self.starttls=starttls.getName()
        if self.starttls=='failure':
            self.DEBUG("Got starttls response: "+self.starttls,'error')
            return
        self.DEBUG("Got starttls proceed response. Switching to TLS/SSL...",'ok')
        self._startSSL()
        self._owner.Dispatcher.PlugOut()
        dispatcher.Dispatcher().PlugIn(self._owner)
