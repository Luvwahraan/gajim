# -*- coding:utf-8 -*-
## src/chat_control_base.py
##
## Copyright (C) 2006 Dimitur Kirov <dkirov AT gmail.com>
## Copyright (C) 2006-2014 Yann Leboulanger <asterix AT lagaule.org>
## Copyright (C) 2006-2008 Jean-Marie Traissard <jim AT lapin.org>
##                         Nikos Kouremenos <kourem AT gmail.com>
##                         Travis Shirk <travis AT pobox.com>
## Copyright (C) 2007 Lukas Petrovicky <lukas AT petrovicky.net>
##                    Julien Pivotto <roidelapluie AT gmail.com>
## Copyright (C) 2007-2008 Brendan Taylor <whateley AT gmail.com>
##                         Stephan Erb <steve-e AT h3c.de>
## Copyright (C) 2008 Jonathan Schleifer <js-gajim AT webkeks.org>
##
## This file is part of Gajim.
##
## Gajim is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published
## by the Free Software Foundation; version 3 only.
##
## Gajim is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Gajim. If not, see <http://www.gnu.org/licenses/>.
##

import os
import time
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Pango
from gi.repository import GObject
from gi.repository import GLib
import gtkgui_helpers
import message_control
import dialogs
import history_window
import notify
import re

from common import events
from common import gajim
from common import helpers
from common import ged
from message_control import MessageControl
from conversation_textview import ConversationTextview
from message_textview import MessageTextView
from common.contacts import GC_Contact
from common.connection_handlers_events import MessageOutgoingEvent

from command_system.implementation.middleware import ChatCommandProcessor
from command_system.implementation.middleware import CommandTools

try:
    import gtkspell
    HAS_GTK_SPELL = True
except (ImportError, ValueError):
    HAS_GTK_SPELL = False

################################################################################
class ChatControlBase(MessageControl, ChatCommandProcessor, CommandTools):
    """
    A base class containing a banner, ConversationTextview, MessageTextView
    """

    keymap = Gdk.Keymap.get_default()
    try:
        keycode_c = keymap.get_entries_for_keyval(Gdk.KEY_c)[1][0].keycode
    except TypeError:
        keycode_c = 54
    try:
        keycode_ins = keymap.get_entries_for_keyval(Gdk.KEY_Insert)[1][0].keycode
    except TypeError:
        keycode_ins = 118
    except IndexError:
        # There is no KEY_Insert (MacOS)
        keycode_ins = None

    def make_href(self, match):
        url_color = gajim.config.get('urlmsgcolor')
        url = match.group()
        if not '://' in url:
            url = 'http://' + url
        return '<a href="%s"><span color="%s">%s</span></a>' % (url,
                url_color, match.group())

    def get_font_attrs(self):
        """
        Get pango font attributes for banner from theme settings
        """
        theme = gajim.config.get('roster_theme')
        bannerfont = gajim.config.get_per('themes', theme, 'bannerfont')
        bannerfontattrs = gajim.config.get_per('themes', theme, 'bannerfontattrs')

        if bannerfont:
            font = Pango.FontDescription(bannerfont)
        else:
            font = Pango.FontDescription('Normal')
        if bannerfontattrs:
            # B attribute is set by default
            if 'B' in bannerfontattrs:
                font.set_weight(Pango.Weight.HEAVY)
            if 'I' in bannerfontattrs:
                font.set_style(Pango.Style.ITALIC)

        font_attrs = 'font_desc="%s"' % font.to_string()

        # in case there is no font specified we use x-large font size
        if font.get_size() == 0:
            font_attrs = '%s size="x-large"' % font_attrs
        font.set_weight(Pango.Weight.NORMAL)
        font_attrs_small = 'font_desc="%s" size="small"' % font.to_string()
        return (font_attrs, font_attrs_small)

    def get_nb_unread(self):
        jid = self.contact.jid
        if self.resource:
            jid += '/' + self.resource
        type_ = self.type_id
        return len(gajim.events.get_events(self.account, jid, ['printed_' + type_,
                type_]))

    def draw_banner(self):
        """
        Draw the fat line at the top of the window that houses the icon, jid, etc

        Derived types MAY implement this.
        """
        self.draw_banner_text()
        self._update_banner_state_image()
        gajim.plugin_manager.gui_extension_point('chat_control_base_draw_banner',
            self)

    def update_toolbar(self):
        """
        update state of buttons in toolbar
        """
        self._update_toolbar()
        gajim.plugin_manager.gui_extension_point(
            'chat_control_base_update_toolbar', self)

    def draw_banner_text(self):
        """
        Derived types SHOULD implement this
        """
        pass

    def update_ui(self):
        """
        Derived types SHOULD implement this
        """
        self.draw_banner()

    def repaint_themed_widgets(self):
        """
        Derived types MAY implement this
        """
        self._paint_banner()
        self.draw_banner()

    def _update_banner_state_image(self):
        """
        Derived types MAY implement this
        """
        pass

    def _update_toolbar(self):
        """
        Derived types MAY implement this
        """
        pass

    def _nec_our_status(self, obj):
        if self.account != obj.conn.name:
            return
        if obj.show == 'offline' or (obj.show == 'invisible' and \
        obj.conn.is_zeroconf):
            self.got_disconnected()
        else:
            # Other code rejoins all GCs, so we don't do it here
            if not self.type_id == message_control.TYPE_GC:
                self.got_connected()
        if self.parent_win:
            self.parent_win.redraw_tab(self)

    def _nec_ping_sent(self, obj):
        if self.contact != obj.contact:
            return
        self.print_conversation(_('Ping?'), 'status')

    def _nec_ping_error(self, obj):
        if self.contact != obj.contact:
            return
        self.print_conversation(_('Error.'), 'status')

    def status_url_clicked(self, widget, url):
        helpers.launch_browser_mailer('url', url)

    def setup_seclabel(self, combo):
        self.seclabel_combo = combo
        self.seclabel_combo.hide()
        self.seclabel_combo.set_no_show_all(True)
        lb = Gtk.ListStore(str)
        self.seclabel_combo.set_model(lb)
        cell = Gtk.CellRendererText()
        cell.set_property('xpad', 5)  # padding for status text
        self.seclabel_combo.pack_start(cell, True)
        # text to show is in in first column of liststore
        self.seclabel_combo.add_attribute(cell, 'text', 0)
        if gajim.connections[self.account].seclabel_supported:
            gajim.connections[self.account].seclabel_catalogue(self.contact.jid, self.on_seclabels_ready)

    def on_seclabels_ready(self):
        lb = self.seclabel_combo.get_model()
        lb.clear()
        i = 0
        sel = 0
        catalogue = gajim.connections[self.account].seclabel_catalogues[
            self.contact.jid]
        for label in catalogue[2]:
            lb.append([label])
            if label == catalogue[3]:
                sel = i
            i += 1
        self.seclabel_combo.set_active(sel)
        self.seclabel_combo.set_no_show_all(False)
        self.seclabel_combo.show_all()

    def __init__(self, type_id, parent_win, widget_name, contact, acct,
    resource=None):
        # Undo needs this variable to know if space has been pressed.
        # Initialize it to True so empty textview is saved in undo list
        self.space_pressed = True

        if resource is None:
            # We very likely got a contact with a random resource.
            # This is bad, we need the highest for caps etc.
            c = gajim.contacts.get_contact_with_highest_priority(acct,
                contact.jid)
            if c and not isinstance(c, GC_Contact):
                contact = c

        MessageControl.__init__(self, type_id, parent_win, widget_name,
            contact, acct, resource=resource)

        widget = self.xml.get_object('history_button')
        # set document-open-recent icon for history button
        if gtkgui_helpers.gtk_icon_theme.has_icon('document-open-recent'):
            img = self.xml.get_object('history_image')
            img.set_from_icon_name('document-open-recent', Gtk.IconSize.MENU)

        id_ = widget.connect('clicked', self._on_history_menuitem_activate)
        self.handlers[id_] = widget

        # when/if we do XHTML we will put formatting buttons back
        widget = self.xml.get_object('emoticons_button')
        widget.set_sensitive(False)
        id_ = widget.connect('clicked', self.on_emoticons_button_clicked)
        self.handlers[id_] = widget

        # Create banner and connect signals
        widget = self.xml.get_object('banner_eventbox')
        id_ = widget.connect('button-press-event',
            self._on_banner_eventbox_button_press_event)
        self.handlers[id_] = widget

        self.urlfinder = re.compile(
            r"(www\.(?!\.)|[a-z][a-z0-9+.-]*://)[^\s<>'\"]+[^!,\.\s<>\)'\"\]]")

        self.banner_status_label = self.xml.get_object('banner_label')
        id_ = self.banner_status_label.connect('populate_popup',
            self.on_banner_label_populate_popup)
        self.handlers[id_] = self.banner_status_label

        # Init DND
        self.TARGET_TYPE_URI_LIST = 80
        self.dnd_list = [Gtk.TargetEntry.new('text/uri-list', 0,
            self.TARGET_TYPE_URI_LIST), Gtk.TargetEntry.new('MY_TREE_MODEL_ROW',
            Gtk.TargetFlags.SAME_APP, 0)]
        id_ = self.widget.connect('drag_data_received',
            self._on_drag_data_received)
        self.handlers[id_] = self.widget
        self.widget.drag_dest_set(Gtk.DestDefaults.MOTION |
            Gtk.DestDefaults.HIGHLIGHT | Gtk.DestDefaults.DROP,
            self.dnd_list, Gdk.DragAction.COPY)

        # Create textviews and connect signals
        self.conv_textview = ConversationTextview(self.account)
        id_ = self.conv_textview.connect('quote', self.on_quote)
        self.handlers[id_] = self.conv_textview.tv
        id_ = self.conv_textview.tv.connect('key_press_event',
            self._conv_textview_key_press_event)
        self.handlers[id_] = self.conv_textview.tv
        # FIXME: DND on non editable TextView, find a better way
        self.drag_entered = False
        id_ = self.conv_textview.tv.connect('drag_data_received',
            self._on_drag_data_received)
        self.handlers[id_] = self.conv_textview.tv
        id_ = self.conv_textview.tv.connect('drag_motion', self._on_drag_motion)
        self.handlers[id_] = self.conv_textview.tv
        id_ = self.conv_textview.tv.connect('drag_leave', self._on_drag_leave)
        self.handlers[id_] = self.conv_textview.tv
        self.conv_textview.tv.drag_dest_set(Gtk.DestDefaults.MOTION |
            Gtk.DestDefaults.HIGHLIGHT | Gtk.DestDefaults.DROP,
            self.dnd_list, Gdk.DragAction.COPY)

        self.conv_scrolledwindow = self.xml.get_object(
            'conversation_scrolledwindow')
        self.conv_scrolledwindow.add(self.conv_textview.tv)
        widget = self.conv_scrolledwindow.get_vadjustment()
        id_ = widget.connect('value-changed',
            self.on_conversation_vadjustment_value_changed)
        self.handlers[id_] = widget
        id_ = widget.connect('changed',
            self.on_conversation_vadjustment_changed)
        self.handlers[id_] = widget
        self.scroll_to_end_id = None
        self.was_at_the_end = True
        self.correcting = False
        self.last_sent_msg = None
        self.last_received_txt = {} # one per name
        self.last_received_id = {} # one per name

        # add MessageTextView to UI and connect signals
        self.msg_scrolledwindow = self.xml.get_object('message_scrolledwindow')
        self.msg_textview = MessageTextView()
        self.msg_scrolledwindow.add(self.msg_textview)
        id_ = self.msg_textview.connect('key_press_event',
            self._on_message_textview_key_press_event)
        self.handlers[id_] = self.msg_textview
        id_ = self.msg_textview.connect('configure-event',
            self.on_configure_event)
        self.handlers[id_] = self.msg_textview
        id_ = self.msg_textview.connect('populate_popup',
            self.on_msg_textview_populate_popup)
        self.handlers[id_] = self.msg_textview
        # Setup DND
        id_ = self.msg_textview.connect('drag_data_received',
            self._on_drag_data_received)
        self.handlers[id_] = self.msg_textview
        self.msg_textview.drag_dest_set(Gtk.DestDefaults.MOTION |
            Gtk.DestDefaults.HIGHLIGHT, self.dnd_list, Gdk.DragAction.COPY)

        self.update_font()

        # Hook up send button
        widget = self.xml.get_object('send_button')
        id_ = widget.connect('clicked', self._on_send_button_clicked)
        widget.set_sensitive(False)
        self.handlers[id_] = widget

        # the following vars are used to keep history of user's messages
        self.sent_history = []
        self.sent_history_pos = 0
        self.received_history = []
        self.received_history_pos = 0
        self.orig_msg = None

        # Emoticons menu
        # set image no matter if user wants at this time emoticons or not
        # (so toggle works ok)
        img = self.xml.get_object('emoticons_button_image')
        img.set_from_file(os.path.join(gajim.DATA_DIR, 'emoticons', 'static',
            'smile.png'))
        self.toggle_emoticons()

        # Attach speller
        if gajim.config.get('use_speller') and HAS_GTK_SPELL:
            self.set_speller()
        self.conv_textview.tv.show()
        self._paint_banner()

        # For XEP-0172
        self.user_nick = None

        self.smooth = True

        self.command_hits = []
        self.last_key_tabs = False

        # PluginSystem: adding GUI extension point for ChatControlBase
        # instance object (also subclasses, eg. ChatControl or GroupchatControl)
        gajim.plugin_manager.gui_extension_point('chat_control_base', self)

        gajim.ged.register_event_handler('our-show', ged.GUI1,
            self._nec_our_status)
        gajim.ged.register_event_handler('ping-sent', ged.GUI1,
            self._nec_ping_sent)
        gajim.ged.register_event_handler('ping-reply', ged.GUI1,
            self._nec_ping_reply)
        gajim.ged.register_event_handler('ping-error', ged.GUI1,
            self._nec_ping_error)

        # This is bascially a very nasty hack to surpass the inability
        # to properly use the super, because of the old code.
        CommandTools.__init__(self)

    def set_speller(self):
        # now set the one the user selected
        per_type = 'contacts'
        if self.type_id == message_control.TYPE_GC:
            per_type = 'rooms'
        lang = gajim.config.get_per(per_type, self.contact.jid,
                'speller_language')
        if not lang:
            # use the default one
            lang = gajim.config.get('speller_language')
            if not lang:
                lang = gajim.LANG
        if lang:
            try:
                self.spell = gtkspell.Spell(self.msg_textview, lang)
                self.msg_textview.lang = lang
                self.spell.connect('language_changed', self.on_language_changed)
            except (GObject.GError, RuntimeError, TypeError, OSError):
                dialogs.AspellDictError(lang)

    def on_language_changed(self, spell, lang):
        per_type = 'contacts'
        if self.type_id == message_control.TYPE_GC:
            per_type = 'rooms'
        if not gajim.config.get_per(per_type, self.contact.jid):
            gajim.config.add_per(per_type, self.contact.jid)
        gajim.config.set_per(per_type, self.contact.jid, 'speller_language',
            lang)
        self.msg_textview.lang = lang

    def on_banner_label_populate_popup(self, label, menu):
        """
        Override the default context menu and add our own menutiems
        """
        item = Gtk.SeparatorMenuItem.new()
        menu.prepend(item)

        menu2 = self.prepare_context_menu()
        i = 0
        for item in menu2:
            menu2.remove(item)
            menu.prepend(item)
            menu.reorder_child(item, i)
            i += 1
        menu.show_all()

    def shutdown(self):
        super(ChatControlBase, self).shutdown()
        # PluginSystem: removing GUI extension points connected with ChatControlBase
        # instance object
        gajim.plugin_manager.remove_gui_extension_point('chat_control_base',
            self)
        gajim.plugin_manager.remove_gui_extension_point(
            'chat_control_base_draw_banner', self)
        gajim.plugin_manager.remove_gui_extension_point('print_special_text',
            self)
        gajim.ged.remove_event_handler('our-show', ged.GUI1,
            self._nec_our_status)

    def on_msg_textview_populate_popup(self, textview, menu):
        """
        Override the default context menu and we prepend an option to switch
        languages
        """
        item = Gtk.MenuItem.new_with_mnemonic(_('_Undo'))
        menu.prepend(item)
        id_ = item.connect('activate', self.msg_textview.undo)
        self.handlers[id_] = item

        item = Gtk.SeparatorMenuItem.new()
        menu.prepend(item)

        item = Gtk.MenuItem.new_with_mnemonic(_('_Clear'))
        menu.prepend(item)
        id_ = item.connect('activate', self.msg_textview.clear)
        self.handlers[id_] = item

        menu.show_all()

    def on_quote(self, widget, text):
        text = '>' + text.replace('\n', '\n>') + '\n'
        message_buffer = self.msg_textview.get_buffer()
        message_buffer.insert_at_cursor(text)

    # moved from ChatControl
    def _on_banner_eventbox_button_press_event(self, widget, event):
        """
        If right-clicked, show popup
        """
        if event.button == 3:  # right click
            self.parent_win.popup_menu(event)

    def _on_send_button_clicked(self, widget):
        """
        When send button is pressed: send the current message
        """
        message_buffer = self.msg_textview.get_buffer()
        start_iter = message_buffer.get_start_iter()
        end_iter = message_buffer.get_end_iter()
        message = message_buffer.get_text(start_iter, end_iter, False)
        xhtml = self.msg_textview.get_xhtml()

        # send the message
        self.send_message(message, xhtml=xhtml)

    def _paint_banner(self):
        """
        Repaint banner with theme color
        """
        theme = gajim.config.get('roster_theme')
        bgcolor = gajim.config.get_per('themes', theme, 'bannerbgcolor')
        textcolor = gajim.config.get_per('themes', theme, 'bannertextcolor')
        # the backgrounds are colored by using an eventbox by
        # setting the bg color of the eventbox and the fg of the name_label
        banner_eventbox = self.xml.get_object('banner_eventbox')
        banner_name_label = self.xml.get_object('banner_name_label')
        self.disconnect_style_event(banner_name_label)
        self.disconnect_style_event(self.banner_status_label)
        if bgcolor:
            color = Gdk.RGBA()
            Gdk.RGBA.parse(color, bgcolor)
            banner_eventbox.override_background_color(Gtk.StateType.NORMAL,
                color)
            default_bg = False
        else:
            default_bg = True
        if textcolor:
            color = Gdk.RGBA()
            Gdk.RGBA.parse(color, textcolor)
            banner_name_label.override_color(Gtk.StateType.NORMAL,
                color)
            self.banner_status_label.override_color(
                Gtk.StateType.NORMAL, color)
            default_fg = False
        else:
            default_fg = True
        if default_bg or default_fg:
            self._on_style_set_event(banner_name_label, None, default_fg,
                    default_bg)
            if self.banner_status_label.get_realized():
                # Widget is realized
                self._on_style_set_event(self.banner_status_label, None, default_fg,
                        default_bg)

    def disconnect_style_event(self, widget):
        # Try to find the event_id
        for id_ in self.handlers.keys():
            if self.handlers[id_] == widget:
                widget.disconnect(id_)
                del self.handlers[id_]
                break

    def connect_style_event(self, widget, set_fg=False, set_bg=False):
        self.disconnect_style_event(widget)
        id_ = widget.connect('style-set', self._on_style_set_event, set_fg,
            set_bg)
        self.handlers[id_] = widget

    def _on_style_set_event(self, widget, style, *opts):
        """
        Set style of widget from style class *.Frame.Eventbox
                opts[0] == True -> set fg color
                opts[1] == True -> set bg color
        """
        banner_eventbox = self.xml.get_object('banner_eventbox')
        self.disconnect_style_event(widget)
        context = widget.get_style_context()
        if opts[1]:
            bg_color = context.get_background_color(Gtk.StateFlags.SELECTED)
            banner_eventbox.override_background_color(Gtk.StateType.NORMAL, bg_color)
        if opts[0]:
            fg_color = context.get_color(Gtk.StateFlags.SELECTED)
            widget.override_color(Gtk.StateType.NORMAL, fg_color)
        self.connect_style_event(widget, opts[0], opts[1])

    def _conv_textview_key_press_event(self, widget, event):
        # translate any layout to latin_layout
        valid, entries = self.keymap.get_entries_for_keyval(event.keyval)
        keycode = entries[0].keycode
        if (event.get_state() & Gdk.ModifierType.CONTROL_MASK and keycode in (
        self.keycode_c, self.keycode_ins)) or (
        event.get_state() & Gdk.ModifierType.SHIFT_MASK and \
        event.keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Page_Up)):
            return False
        self.parent_win.notebook.event(event)
        return True

    def show_emoticons_menu(self):
        if not gajim.config.get('emoticons_theme'):
            return
        gajim.interface.emoticon_menuitem_clicked = self.append_emoticon
        gajim.interface.emoticons_menu.popup(None, None, None, None, 1, 0)

    def _on_message_textview_key_press_event(self, widget, event):
        if event.keyval == Gdk.KEY_space:
            self.space_pressed = True

        elif (self.space_pressed or self.msg_textview.undo_pressed) and \
        event.keyval not in (Gdk.KEY_Control_L, Gdk.KEY_Control_R) and \
        not (event.keyval == Gdk.KEY_z and event.get_state() & Gdk.ModifierType.CONTROL_MASK):
            # If the space key has been pressed and now it hasnt,
            # we save the buffer into the undo list. But be carefull we're not
            # pressiong Control again (as in ctrl+z)
            _buffer = widget.get_buffer()
            start_iter, end_iter = _buffer.get_bounds()
            self.msg_textview.save_undo(_buffer.get_text(start_iter, end_iter, True))
            self.space_pressed = False

        # Ctrl [+ Shift] + Tab are not forwarded to notebook. We handle it here
        if self.widget_name == 'groupchat_control':
            if event.keyval not in (Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Tab):
                self.last_key_tabs = False
        if event.get_state() & Gdk.ModifierType.SHIFT_MASK:
            # CTRL + SHIFT + TAB
            if event.get_state() & Gdk.ModifierType.CONTROL_MASK and \
                            event.keyval == Gdk.KEY_ISO_Left_Tab:
                self.parent_win.move_to_next_unread_tab(False)
                return True
            # SHIFT + PAGE_[UP|DOWN]: send to conv_textview
            elif event.keyval == Gdk.KEY_Page_Down or \
                            event.keyval == Gdk.KEY_Page_Up:
                self.conv_textview.tv.event(event)
                return True
        elif event.get_state() & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval == Gdk.KEY_Tab:  # CTRL + TAB
                self.parent_win.move_to_next_unread_tab(True)
                return True

        message_buffer = self.msg_textview.get_buffer()
        event_state = event.get_state()
        if event.keyval == Gdk.KEY_Tab:
            start, end = message_buffer.get_bounds()
            position = message_buffer.get_insert()
            end = message_buffer.get_iter_at_mark(position)
            text = message_buffer.get_text(start, end, False)
            splitted = text.split()
            if (text.startswith(self.COMMAND_PREFIX) and not
            text.startswith(self.COMMAND_PREFIX * 2) and len(splitted) == 1):
                text = splitted[0]
                bare = text.lstrip(self.COMMAND_PREFIX)
                if len(text) == 1:
                    self.command_hits = []
                    for command in self.list_commands():
                        for name in command.names:
                            self.command_hits.append(name)
                else:
                    if (self.last_key_tabs and self.command_hits and
                            self.command_hits[0].startswith(bare)):
                        self.command_hits.append(self.command_hits.pop(0))
                    else:
                        self.command_hits = []
                        for command in self.list_commands():
                            for name in command.names:
                                if name.startswith(bare):
                                    self.command_hits.append(name)

                if self.command_hits:
                    message_buffer.delete(start, end)
                    message_buffer.insert_at_cursor(self.COMMAND_PREFIX + \
                        self.command_hits[0] + ' ')
                    self.last_key_tabs = True
                return True
            if self.widget_name != 'groupchat_control':
                self.last_key_tabs = False
        if event.keyval == Gdk.KEY_Up:
            if event_state & Gdk.ModifierType.CONTROL_MASK:
                if event_state & Gdk.ModifierType.SHIFT_MASK: # Ctrl+Shift+UP
                    self.scroll_messages('up', message_buffer, 'received')
                else:  # Ctrl+UP
                    self.scroll_messages('up', message_buffer, 'sent')
                return True
        elif event.keyval == Gdk.KEY_Down:
            if event_state & Gdk.ModifierType.CONTROL_MASK:
                if event_state & Gdk.ModifierType.SHIFT_MASK: # Ctrl+Shift+Down
                    self.scroll_messages('down', message_buffer, 'received')
                else:  # Ctrl+Down
                    self.scroll_messages('down', message_buffer, 'sent')
                return True
        elif event.keyval == Gdk.KEY_Return or \
        event.keyval == Gdk.KEY_KP_Enter:  # ENTER
            message_textview = widget
            message_buffer = message_textview.get_buffer()
            start_iter, end_iter = message_buffer.get_bounds()
            message = message_buffer.get_text(start_iter, end_iter, False)
            xhtml = self.msg_textview.get_xhtml()

            if event_state & Gdk.ModifierType.SHIFT_MASK:
                send_message = False
            else:
                is_ctrl_enter = bool(event_state & Gdk.ModifierType.CONTROL_MASK)
                send_message = is_ctrl_enter == gajim.config.get('send_on_ctrl_enter')

            if send_message and gajim.connections[self.account].connected < 2:
                # we are not connected
                dialogs.ErrorDialog(_('A connection is not available'),
                    _('Your message can not be sent until you are connected.'))
            elif send_message:
                self.send_message(message, xhtml=xhtml)
            else:
                message_buffer.insert_at_cursor('\n')

            return True
        elif event.keyval == Gdk.KEY_z: # CTRL+z
            if event_state & Gdk.ModifierType.CONTROL_MASK:
                self.msg_textview.undo()
                return True

        return False

    def _on_drag_data_received(self, widget, context, x, y, selection,
                    target_type, timestamp):
        """
        Derived types SHOULD implement this
        """
        pass

    def _on_drag_leave(self, widget, context, time):
        # FIXME: DND on non editable TextView, find a better way
        self.drag_entered = False
        self.conv_textview.tv.set_editable(False)

    def _on_drag_motion(self, widget, context, x, y, time):
        # FIXME: DND on non editable TextView, find a better way
        if not self.drag_entered:
            # We drag new data over the TextView, make it editable to catch dnd
            self.drag_entered_conv = True
            self.conv_textview.tv.set_editable(True)

    def get_seclabel(self):
        label = None
        if self.seclabel_combo is not None:
            idx = self.seclabel_combo.get_active()
            if idx != -1:
                cat = gajim.connections[self.account].seclabel_catalogues[self.contact.jid]
                lname = cat[2][idx]
                label = cat[1][lname]
        return label

    def send_message(self, message, keyID='', type_='chat', chatstate=None,
    msg_id=None, resource=None, xhtml=None, callback=None, callback_args=None,
    process_commands=True, attention=False):
        """
        Send the given message to the active tab. Doesn't return None if error
        """
        if not message or message == '\n':
            return None

        if callback_args is None:
            callback_args = []

        if process_commands and self.process_as_command(message):
            return

        label = self.get_seclabel()

        def _cb(obj, msg, cb, *cb_args):
            self.last_sent_msg = msg
            if cb:
                cb(obj, msg, *cb_args)

        if self.correcting and self.last_sent_msg:
            correction_msg = self.last_sent_msg
        else:
            correction_msg = None

        gajim.nec.push_outgoing_event(MessageOutgoingEvent(None,
            account=self.account, jid=self.contact.jid, message=message,
            keyID=keyID, type_=type_, chatstate=chatstate, msg_id=msg_id,
            resource=resource, user_nick=self.user_nick, xhtml=xhtml,
            label=label, callback=_cb, callback_args=[callback] + callback_args,
            control=self, attention=attention, correction_msg=correction_msg, automatic_message=False))

        # Record the history of sent messages
        self.save_message(message, 'sent')

        # Be sure to send user nickname only once according to JEP-0172
        self.user_nick = None

        # Clear msg input
        message_buffer = self.msg_textview.get_buffer()
        message_buffer.set_text('') # clear message buffer (and tv of course)

    def save_message(self, message, msg_type):
        # save the message, so user can scroll though the list with key up/down
        if msg_type == 'sent':
            history = self.sent_history
            pos = self.sent_history_pos
        else:
            history = self.received_history
            pos = self.received_history_pos
        size = len(history)
        scroll = False if pos == size else True # are we scrolling?
        # we don't want size of the buffer to grow indefinately
        max_size = gajim.config.get('key_up_lines')
        for i in range(size - max_size + 1):
            if pos == 0:
                break
            history.pop(0)
            pos -= 1
        history.append(message)
        if not scroll or msg_type == 'sent':
            pos = len(history)
        if msg_type == 'sent':
            self.sent_history_pos = pos
            self.orig_msg = None
        else:
            self.received_history_pos = pos

    def print_conversation_line(self, text, kind, name, tim,
    other_tags_for_name=[], other_tags_for_time=[], other_tags_for_text=[],
    count_as_new=True, subject=None, old_kind=None, xhtml=None, simple=False,
    xep0184_id=None, graphics=True, displaymarking=None, msg_log_id=None,
    msg_stanza_id=None, correct_id=None, additional_data=None):
        """
        Print 'chat' type messages
        correct_id = (message_id, correct_id)
        """
        jid = self.contact.jid
        full_jid = self.get_full_jid()
        textview = self.conv_textview
        end = False
        if self.was_at_the_end or kind == 'outgoing':
            end = True

        if other_tags_for_name is None:
            other_tags_for_name = []
        if other_tags_for_time is None:
            other_tags_for_time = []
        if other_tags_for_text is None:
            other_tags_for_text = []
        if additional_data is None:
            additional_data = {}

        textview.print_conversation_line(text, jid, kind, name, tim,
            other_tags_for_name, other_tags_for_time, other_tags_for_text,
            subject, old_kind, xhtml, simple=simple, graphics=graphics,
            displaymarking=displaymarking, msg_stanza_id=msg_stanza_id,
            correct_id=correct_id, additional_data=additional_data)

        if xep0184_id is not None:
            textview.show_xep0184_warning(xep0184_id)

        if not count_as_new:
            return
        if kind in ('incoming', 'incoming_queue', 'outgoing'):
            self.last_received_txt[name] = text
            if correct_id:
                self.last_received_id[name] = correct_id[0]
        if kind == 'incoming':
            if not self.type_id == message_control.TYPE_GC or \
            gajim.config.get('notify_on_all_muc_messages') or \
            'marked' in other_tags_for_text:
                # it's a normal message, or a muc message with want to be
                # notified about if quitting just after
                # other_tags_for_text == ['marked'] --> highlighted gc message
                gajim.last_message_time[self.account][full_jid] = time.time()

        if kind in ('incoming', 'incoming_queue'):
            # Record the history of received messages
            self.save_message(text, 'received')

        if kind in ('incoming', 'incoming_queue', 'error'):
            gc_message = False
            if self.type_id == message_control.TYPE_GC:
                gc_message = True

            if ((self.parent_win and (not self.parent_win.get_active_control() or \
            self != self.parent_win.get_active_control() or \
            not self.parent_win.is_active() or not end)) or \
            (gc_message and \
            jid in gajim.interface.minimized_controls[self.account])) and \
            kind in ('incoming', 'incoming_queue', 'error'):
                # we want to have save this message in events list
                # other_tags_for_text == ['marked'] --> highlighted gc message
                if gc_message:
                    if 'marked' in other_tags_for_text:
                        event_type = events.PrintedMarkedGcMsgEvent
                    else:
                        event_type = events.PrintedGcMsgEvent
                    event = 'gc_message_received'
                else:
                    if self.type_id == message_control.TYPE_CHAT:
                        event_type = events.PrintedChatEvent
                    else:
                        event_type = events.PrintedPmEvent
                    event = 'message_received'
                show_in_roster = notify.get_show_in_roster(event,
                    self.account, self.contact, self.session)
                show_in_systray = notify.get_show_in_systray(event,
                    self.account, self.contact, event_type.type_)

                event = event_type(text, subject, self, msg_log_id,
                    show_in_roster=show_in_roster,
                    show_in_systray=show_in_systray)
                gajim.events.add_event(self.account, full_jid, event)
                # We need to redraw contact if we show in roster
                if show_in_roster:
                    gajim.interface.roster.draw_contact(self.contact.jid,
                        self.account)

        if not self.parent_win:
            return

        if (not self.parent_win.get_active_control() or \
        self != self.parent_win.get_active_control() or \
        not self.parent_win.is_active() or not end) and \
        kind in ('incoming', 'incoming_queue', 'error'):
            self.parent_win.redraw_tab(self)
            if not self.parent_win.is_active():
                self.parent_win.show_title(True, self) # Enabled Urgent hint
            else:
                self.parent_win.show_title(False, self) # Disabled Urgent hint

    def toggle_emoticons(self):
        """
        Hide show emoticons_button and make sure emoticons_menu is always there
        when needed
        """
        emoticons_button = self.xml.get_object('emoticons_button')
        if gajim.config.get('emoticons_theme'):
            emoticons_button.show()
            emoticons_button.set_no_show_all(False)
        else:
            emoticons_button.hide()
            emoticons_button.set_no_show_all(True)

    def append_emoticon(self, str_):
        buffer_ = self.msg_textview.get_buffer()
        if buffer_.get_char_count():
            buffer_.insert_at_cursor(' %s ' % str_)
        else: # we are the beginning of buffer
            buffer_.insert_at_cursor('%s ' % str_)
        self.msg_textview.grab_focus()

    def on_emoticons_button_clicked(self, widget):
        """
        Popup emoticons menu
        """
        gajim.interface.emoticon_menuitem_clicked = self.append_emoticon
        gajim.interface.popup_emoticons_under_button(widget, self.parent_win)

    def on_color_menuitem_activate(self, widget):
        color_dialog = Gtk.ColorChooserDialog(None, self.parent_win.window)
        color_dialog.set_use_alpha(False)
        color_dialog.connect('response', self.msg_textview.color_set)
        color_dialog.show_all()

    def on_font_menuitem_activate(self, widget):
        font_dialog = Gtk.FontChooserDialog(None, self.parent_win.window)
        start, finish = self.msg_textview.get_active_iters()
        font_dialog.connect('response', self.msg_textview.font_set, start, finish)
        font_dialog.show_all()

    def on_formatting_menuitem_activate(self, widget):
        tag = widget.get_name()
        self.msg_textview.set_tag(tag)

    def on_clear_formatting_menuitem_activate(self, widget):
        self.msg_textview.clear_tags()

    def on_actions_button_clicked(self, widget):
        """
        Popup action menu
        """
        menu = self.prepare_context_menu(hide_buttonbar_items=True)
        menu.show_all()
        menu.attach_to_widget(widget, None)
        gtkgui_helpers.popup_emoticons_under_button(menu, widget,
                self.parent_win)

    def update_font(self):
        font = Pango.FontDescription(gajim.config.get('conversation_font'))
        self.conv_textview.tv.override_font(font)
        self.msg_textview.override_font(font)

    def update_tags(self):
        self.conv_textview.update_tags()

    def clear(self, tv):
        buffer_ = tv.get_buffer()
        start, end = buffer_.get_bounds()
        buffer_.delete(start, end)

    def _on_history_menuitem_activate(self, widget=None, jid=None):
        """
        When history menuitem is pressed: call history window
        """
        if not jid:
            jid = self.contact.jid

        if 'logs' in gajim.interface.instances:
            gajim.interface.instances['logs'].window.present()
            gajim.interface.instances['logs'].open_history(jid, self.account)
        else:
            gajim.interface.instances['logs'] = \
                    history_window.HistoryWindow(jid, self.account)

    def _on_send_file(self, gc_contact=None):
        """
        gc_contact can be set when we are in a groupchat control
        """
        def _on_ok(c):
            gajim.interface.instances['file_transfers'].show_file_send_request(
                    self.account, c)
        if self.TYPE_ID == message_control.TYPE_PM:
            gc_contact = self.gc_contact
        if gc_contact:
            # gc or pm
            gc_control = gajim.interface.msg_win_mgr.get_gc_control(
                    gc_contact.room_jid, self.account)
            self_contact = gajim.contacts.get_gc_contact(self.account,
                    gc_control.room_jid, gc_control.nick)
            if gc_control.is_anonymous and gc_contact.affiliation not in ['admin',
            'owner'] and self_contact.affiliation in ['admin', 'owner']:
                contact = gajim.contacts.get_contact(self.account, gc_contact.jid)
                if not contact or contact.sub not in ('both', 'to'):
                    prim_text = _('Really send file?')
                    sec_text = _('If you send a file to %s, he/she will know your '
                            'real JID.') % gc_contact.name
                    dialog = dialogs.NonModalConfirmationDialog(prim_text,
                        sec_text, on_response_ok=(_on_ok, gc_contact))
                    dialog.popup()
                    return
            _on_ok(gc_contact)
            return
        _on_ok(self.contact)

    def on_minimize_menuitem_toggled(self, widget):
        """
        When a grouchat is minimized, unparent the tab, put it in roster etc
        """
        old_value = True
        non_minimized_gc = gajim.config.get_per('accounts', self.account,
                'non_minimized_gc').split()
        if self.contact.jid in non_minimized_gc:
            old_value = False
        minimize = widget.get_active()
        if not minimize and not self.contact.jid in non_minimized_gc:
            non_minimized_gc.append(self.contact.jid)
        if minimize and self.contact.jid in non_minimized_gc:
            non_minimized_gc.remove(self.contact.jid)
        if old_value != minimize:
            gajim.config.set_per('accounts', self.account, 'non_minimized_gc',
                    ' '.join(non_minimized_gc))

    def set_control_active(self, state):
        if state:
            jid = self.contact.jid
            if self.was_at_the_end:
                # we are at the end
                type_ = ['printed_' + self.type_id]
                if self.type_id == message_control.TYPE_GC:
                    type_ = ['printed_gc_msg', 'printed_marked_gc_msg']
                if not gajim.events.remove_events(self.account, self.get_full_jid(),
                types=type_):
                    # There were events to remove
                    self.redraw_after_event_removed(jid)

    def bring_scroll_to_end(self, textview, diff_y=0):
        """
        Scroll to the end of textview if end is not visible
        """
        if self.scroll_to_end_id:
            # a scroll is already planned
            return
        buffer_ = textview.get_buffer()
        end_iter = buffer_.get_end_iter()
        end_rect = textview.get_iter_location(end_iter)
        visible_rect = textview.get_visible_rect()
        # scroll only if expected end is not visible
        if end_rect.y >= (visible_rect.y + visible_rect.height + diff_y):
            self.scroll_to_end_id = GLib.idle_add(self.scroll_to_end_iter,
                    textview)

    def scroll_to_end_iter(self, textview):
        buffer_ = textview.get_buffer()
        end_iter = buffer_.get_end_iter()
        textview.scroll_to_iter(end_iter, 0, False, 1, 1)
        self.scroll_to_end_id = None
        return False

    def on_configure_event(self, msg_textview, event):
        """
        When message_textview changes its size: if the new height will enlarge
        the window, enable the scrollbar automatic policy.  Also enable scrollbar
        automatic policy for horizontal scrollbar if message we have in
        message_textview is too big
        """
        if msg_textview.get_window() is None:
            return

        min_height = self.conv_scrolledwindow.get_property('height-request')
        conversation_height = self.conv_textview.tv.get_window().get_size()[1]
        message_height = msg_textview.get_window().get_size()[1]
        message_width = msg_textview.get_window().get_size()[0]
        # new tab is not exposed yet
        if conversation_height < 2:
            return

        if conversation_height < min_height:
            min_height = conversation_height

        # we don't want to always resize in height the message_textview
        # so we have minimum on conversation_textview's scrolled window
        # but we also want to avoid window resizing so if we reach that
        # minimum for conversation_textview and maximum for message_textview
        # we set to automatic the scrollbar policy
        diff_y = message_height - event.height
        if diff_y != 0:
            if conversation_height + diff_y < min_height:
                if message_height + conversation_height - min_height > min_height:
                    policy = self.msg_scrolledwindow.get_property(
                            'vscrollbar-policy')
                    if policy != Gtk.PolicyType.AUTOMATIC:
                        self.msg_scrolledwindow.set_property('vscrollbar-policy',
                                Gtk.PolicyType.AUTOMATIC)
                        self.msg_scrolledwindow.set_property('height-request',
                                message_height + conversation_height - min_height)
            else:
                self.msg_scrolledwindow.set_property('vscrollbar-policy',
                        Gtk.PolicyType.NEVER)
                self.msg_scrolledwindow.set_property('height-request', -1)

        self.smooth = True # reinit the flag
        # enable scrollbar automatic policy for horizontal scrollbar
        # if message we have in message_textview is too big
        if event.width > message_width:
            self.msg_scrolledwindow.set_property('hscrollbar-policy',
                    Gtk.PolicyType.AUTOMATIC)
        else:
            self.msg_scrolledwindow.set_property('hscrollbar-policy',
                    Gtk.PolicyType.NEVER)

        return True

    def on_conversation_vadjustment_changed(self, adjustment):
        # used to stay at the end of the textview when we shrink conversation
        # textview.
        if self.was_at_the_end:
            if self.conv_textview.at_the_end():
                # we are at the end
                self.conv_textview.bring_scroll_to_end(-18)
            else:
                self.conv_textview.bring_scroll_to_end(-18, use_smooth=False)
        self.was_at_the_end = (adjustment.get_upper() - adjustment.get_value()\
            - adjustment.get_page_size()) < 18

    def on_conversation_vadjustment_value_changed(self, adjustment):
        # stop automatic scroll when we manually scroll
        if not self.conv_textview.auto_scrolling:
            self.conv_textview.stop_scrolling()
        self.was_at_the_end = (adjustment.get_upper() - adjustment.get_value() \
            - adjustment.get_page_size()) < 18
        if self.resource:
            jid = self.contact.get_full_jid()
        else:
            jid = self.contact.jid
        types_list = []
        type_ = self.type_id
        if type_ == message_control.TYPE_GC:
            type_ = 'gc_msg'
            types_list = ['printed_' + type_, type_, 'printed_marked_gc_msg']
        else: # Not a GC
            types_list = ['printed_' + type_, type_]

        if not len(gajim.events.get_events(self.account, jid, types_list)):
            return
        if not self.parent_win:
            return
        if self.conv_textview.at_the_end() and \
        self.parent_win.get_active_control() == self and \
        self.parent_win.window.is_active():
            # we are at the end
            if self.type_id == message_control.TYPE_GC:
                if not gajim.events.remove_events(self.account, jid,
                types=types_list):
                    self.redraw_after_event_removed(jid)
            elif self.session and self.session.remove_events(types_list):
                # There were events to remove
                self.redraw_after_event_removed(jid)

    def redraw_after_event_removed(self, jid):
        """
        We just removed a 'printed_*' event, redraw contact in roster or
        gc_roster and titles in roster and msg_win
        """
        self.parent_win.redraw_tab(self)
        self.parent_win.show_title()
        # TODO : get the contact and check notify.get_show_in_roster()
        if self.type_id == message_control.TYPE_PM:
            room_jid, nick = gajim.get_room_and_nick_from_fjid(jid)
            groupchat_control = gajim.interface.msg_win_mgr.get_gc_control(
                    room_jid, self.account)
            if room_jid in gajim.interface.minimized_controls[self.account]:
                groupchat_control = \
                        gajim.interface.minimized_controls[self.account][room_jid]
            contact = gajim.contacts.get_contact_with_highest_priority(
                self.account, room_jid)
            if contact:
                gajim.interface.roster.draw_contact(room_jid, self.account)
            if groupchat_control:
                groupchat_control.draw_contact(nick)
                if groupchat_control.parent_win:
                    groupchat_control.parent_win.redraw_tab(groupchat_control)
        else:
            gajim.interface.roster.draw_contact(jid, self.account)
            gajim.interface.roster.show_title()

    def scroll_messages(self, direction, msg_buf, msg_type):
        if msg_type == 'sent':
            history = self.sent_history
            pos = self.sent_history_pos
            self.received_history_pos = len(self.received_history)
        else:
            history = self.received_history
            pos = self.received_history_pos
            self.sent_history_pos = len(self.sent_history)
        size = len(history)
        if self.orig_msg is None:
            # user was typing something and then went into history, so save
            # whatever is already typed
            start_iter = msg_buf.get_start_iter()
            end_iter = msg_buf.get_end_iter()
            self.orig_msg = msg_buf.get_text(start_iter, end_iter, False)
        if pos == size and size > 0 and direction == 'up' and \
        msg_type == 'sent' and not self.correcting and (not \
        history[pos - 1].startswith('/') or history[pos - 1].startswith('/me')):
            self.correcting = True
            context = self.msg_textview.get_style_context()
            state = Gtk.StateFlags.NORMAL
            self.old_message_tv_color = context.get_background_color(state)
            color = Gdk.RGBA()
            Gdk.RGBA.parse(color, 'PaleGoldenrod')
            self.msg_textview.override_background_color(Gtk.StateType.NORMAL,
                color)
            message = history[pos - 1]
            msg_buf.set_text(message)
            return
        if self.correcting:
            # We were previously correcting
            self.msg_textview.override_background_color(Gtk.StateType.NORMAL,
                self.old_message_tv_color)
        self.correcting = False
        pos += -1 if direction == 'up' else +1
        if pos == -1:
            return
        if pos >= size:
            pos = size
            message = self.orig_msg
            self.orig_msg = None
        else:
            message = history[pos]
        if msg_type == 'sent':
            self.sent_history_pos = pos
        else:
            self.received_history_pos = pos
            if self.orig_msg is not None:
                message = '> %s\n' % message.replace('\n', '\n> ')
        msg_buf.set_text(message)

    def lighten_color(self, color):
        p = 0.4
        mask = 0
        color.red = int((color.red * p) + (mask * (1 - p)))
        color.green = int((color.green * p) + (mask * (1 - p)))
        color.blue = int((color.blue * p) + (mask * (1 - p)))
        return color

    def widget_set_visible(self, widget, state):
        """
        Show or hide a widget
        """
        # make the last message visible, when changing to "full view"
        if not state:
            GLib.idle_add(self.conv_textview.scroll_to_end_iter)

        widget.set_no_show_all(state)
        if state:
            widget.hide()
        else:
            widget.show_all()

    def chat_buttons_set_visible(self, state):
        """
        Toggle chat buttons
        """
        MessageControl.chat_buttons_set_visible(self, state)
        self.widget_set_visible(self.xml.get_object('actions_hbox'), state)

    def got_connected(self):
        self.msg_textview.set_sensitive(True)
        self.msg_textview.set_editable(True)
        self.update_toolbar()

    def got_disconnected(self):
        self.msg_textview.set_sensitive(False)
        self.msg_textview.set_editable(False)
        self.conv_textview.tv.grab_focus()

        self.no_autonegotiation = False
        self.update_toolbar()
