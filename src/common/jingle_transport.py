##
## Copyright (C) 2006 Gajim Team
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

"""
Handles Jingle Transports (currently only ICE-UDP)
"""

import xmpp
import socket
from common import gajim
from common.protocol.bytestream import ConnectionSocks5Bytestream
import logging

log = logging.getLogger('gajim.c.jingle_transport')


transports = {}

def get_jingle_transport(node):
    namespace = node.getNamespace()
    if namespace in transports:
        return transports[namespace]()


class TransportType(object):
    """
    Possible types of a JingleTransport
    """
    datagram = 1
    streaming = 2


class JingleTransport(object):
    """
    An abstraction of a transport in Jingle sessions
    """

    def __init__(self, type_):
        self.type = type_
        self.candidates = []
        self.remote_candidates = []

    def _iter_candidates(self):
        for candidate in self.candidates:
            yield self.make_candidate(candidate)

    def make_candidate(self, candidate):
        """
        Build a candidate stanza for the given candidate
        """
        pass

    def make_transport(self, candidates=None):
        """
        Build a transport stanza with the given candidates (or self.candidates if
        candidates is None)
        """
        if not candidates:
            candidates = self._iter_candidates()
        else:
            candidates = (self.make_candidate(candidate) for candidate in candidates)
        transport = xmpp.Node('transport', payload=candidates)
        return transport

    def parse_transport_stanza(self, transport):
        """
        Return the list of transport candidates from a transport stanza
        """
        return []

class JingleTransportSocks5(JingleTransport):
    """
    Socks5 transport in jingle scenario
    Note: Don't forget to call set_file_props after initialization
    """
    def __init__(self):
        JingleTransport.__init__(self, TransportType.streaming)
        self.remote_candidates = []

    def set_file_props(self, file_props):
        self.file_props = file_props

    def set_our_jid(self, jid):
        self.ourjid = jid
        
    def make_candidate(self, candidate):
        import logging
        log = logging.getLogger()
        log.info('candidate dict, %s' % candidate)
        attrs = {
            'cid': candidate['candidate_id'],
            'host': candidate['host'],
            'jid': candidate['jid'],
            'port': candidate['port'],
            'priority': candidate['priority'],
            'type': candidate['type']
        }

        return xmpp.Node('candidate', attrs=attrs)

    def make_transport(self, candidates=None):
        self._add_local_ips_as_candidates()
        self._add_additional_candidates()
        self._add_proxy_candidates()
        transport = JingleTransport.make_transport(self, candidates)
        transport.setNamespace(xmpp.NS_JINGLE_BYTESTREAM)
        return transport

    def parse_transport_stanza(self, transport):
        candidates = []
        for candidate in transport.iterTags('candidate'):
            cand = {
                'state': 0,
                'target': self.ourjid,
                'host': candidate['host'],
                'port': candidate['port']
            }
            candidates.append(cand)
            
            # we need this when we construct file_props on session-initiation
        self.remote_candidates = candidates
        return candidates
            

    def _add_local_ips_as_candidates(self):
        local_ip_cand = []
        port = gajim.config.get('file_transfers_port')
        type_preference = 126 #type preference of connection type. XEP-0260 section 2.2
        jid_wo_resource = gajim.get_jid_without_resource(self.ourjid)
        conn = gajim.connections[jid_wo_resource]
        c = {'host': conn.peerhost[0]}
        c['candidate_id'] = conn.connection.getAnID()
        c['port'] = port
        c['type'] = 'direct'
        c['jid'] = self.ourjid
        c['priority'] = (2**16) * type_preference
        
        local_ip_cand.append(c)
        
        for addr in socket.getaddrinfo(socket.gethostname(), None):
            if not addr[4][0] in local_ip_cand and not addr[4][0].startswith('127'):
                c = {'host': addr[4][0]}
                c['candidate_id'] = conn.connection.getAnID()
                c['port'] = port
                c['type'] = 'direct'
                c['jid'] = self.ourjid
                c['priority'] = (2**16) * type_preference
                local_ip_cand.append(c)

        self.candidates += local_ip_cand

    def _add_additional_candidates(self):
        type_preference = 126
        additional_ip_cand = []
        port = gajim.config.get('file_transfers_port')
        ft_add_hosts = gajim.config.get('ft_add_hosts_to_send')   
        jid_wo_resource = gajim.get_jid_without_resource(self.ourjid)
        conn = gajim.connections[jid_wo_resource]
        
        if ft_add_hosts:
            hosts = [e.strip() for e in ft_add_hosts.split(',')]
            for h in hosts:
                c = {'host': h}
                c['candidate_id'] = conn.connection.getAnID()
                c['port'] = port
                c['type'] = 'direct'
                c['jid'] = self.ourjid
                c['priority'] = (2**16) * type_preference
                additional_ip_cand.append(c)
        self.candidates += additional_ip_cand
        
    def _add_proxy_candidates(self):
        type_preference = 10
        proxy_cand = []
        socks5conn = ConnectionSocks5Bytestream()
        socks5conn.name = self.ourjid
        proxyhosts = socks5conn._get_file_transfer_proxies_from_config(self.file_props)
        jid_wo_resource = gajim.get_jid_without_resource(self.ourjid)
        conn = gajim.connections[jid_wo_resource]

        if proxyhosts:
            file_props['proxy_receiver'] = unicode(file_props['receiver'])
            file_props['proxy_sender'] = unicode(file_props['sender'])
            file_props['proxyhosts'] = proxyhosts
            
            for proxyhost in proxyhosts:
                c = {'host': proxyhost['host']}
                c['candidate_id'] = conn.connection.getAnID()
                c['port'] = proxyhost['port']
                c['type'] = 'proxy'
                c['jid'] = self.ourjid
                c['priority'] = (2**16) * type_preference
                proxy_cand.append(c)
        self.candidates += proxy_cand
        

import farsight

class JingleTransportICEUDP(JingleTransport):
    def __init__(self):
        JingleTransport.__init__(self, TransportType.datagram)

    def make_candidate(self, candidate):
        types = {farsight.CANDIDATE_TYPE_HOST: 'host',
                farsight.CANDIDATE_TYPE_SRFLX: 'srflx',
                farsight.CANDIDATE_TYPE_PRFLX: 'prflx',
                farsight.CANDIDATE_TYPE_RELAY: 'relay',
                farsight.CANDIDATE_TYPE_MULTICAST: 'multicast'}
        attrs = {
                'component': candidate.component_id,
                'foundation': '1', # hack
                'generation': '0',
                'ip': candidate.ip,
                'network': '0',
                'port': candidate.port,
                'priority': int(candidate.priority), # hack
        }
        if candidate.type in types:
            attrs['type'] = types[candidate.type]
        if candidate.proto == farsight.NETWORK_PROTOCOL_UDP:
            attrs['protocol'] = 'udp'
        else:
            # we actually don't handle properly different tcp options in jingle
            attrs['protocol'] = 'tcp'
        return xmpp.Node('candidate', attrs=attrs)

    def make_transport(self, candidates=None):
        transport = JingleTransport.make_transport(self, candidates)
        transport.setNamespace(xmpp.NS_JINGLE_ICE_UDP)
        if self.candidates and self.candidates[0].username and \
                self.candidates[0].password:
            transport.setAttr('ufrag', self.candidates[0].username)
            transport.setAttr('pwd', self.candidates[0].password)
        return transport

    def parse_transport_stanza(self, transport):
        candidates = []
        for candidate in transport.iterTags('candidate'):
            cand = farsight.Candidate()
            cand.component_id = int(candidate['component'])
            cand.ip = str(candidate['ip'])
            cand.port = int(candidate['port'])
            cand.foundation = str(candidate['foundation'])
            #cand.type = farsight.CANDIDATE_TYPE_LOCAL
            cand.priority = int(candidate['priority'])

            if candidate['protocol'] == 'udp':
                cand.proto = farsight.NETWORK_PROTOCOL_UDP
            else:
                # we actually don't handle properly different tcp options in jingle
                cand.proto = farsight.NETWORK_PROTOCOL_TCP

            cand.username = str(transport['ufrag'])
            cand.password = str(transport['pwd'])

            #FIXME: huh?
            types = {'host': farsight.CANDIDATE_TYPE_HOST,
                                    'srflx': farsight.CANDIDATE_TYPE_SRFLX,
                                    'prflx': farsight.CANDIDATE_TYPE_PRFLX,
                                    'relay': farsight.CANDIDATE_TYPE_RELAY,
                                    'multicast': farsight.CANDIDATE_TYPE_MULTICAST}
            if 'type' in candidate and candidate['type'] in types:
                cand.type = types[candidate['type']]
            else:
                print 'Unknown type %s', candidate['type']
            candidates.append(cand)
        self.remote_candidates.extend(candidates)
        return candidates

transports[xmpp.NS_JINGLE_ICE_UDP] = JingleTransportICEUDP
transports[xmpp.NS_JINGLE_BYTESTREAM] = JingleTransportSocks5
