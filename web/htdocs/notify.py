#!/usr/bin/python
# -*- encoding: utf-8; py-indent-offset: 4 -*-
# +------------------------------------------------------------------+
# |             ____ _               _        __  __ _  __           |
# |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
# |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
# |           | |___| | | |  __/ (__|   <    | |  | | . \            |
# |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
# |                                                                  |
# | Copyright Mathias Kettner 2013             mk@mathias-kettner.de |
# +------------------------------------------------------------------+
#
# This file is part of Check_MK.
# The official homepage is at http://mathias-kettner.de/check_mk.
#
# check_mk is free software;  you can redistribute it and/or modify it
# under the  terms of the  GNU General Public License  as published by
# the Free Software Foundation in version 2.  check_mk is  distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
# out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
# PARTICULAR PURPOSE. See the  GNU General Public License for more de-
# ails.  You should have  received  a copy of the  GNU  General Public
# License along with GNU Make; see the file  COPYING.  If  not,  write
# to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
# Boston, MA 02110-1301 USA.

import config, forms, time, lib, userdb
from valuespec import *

def get_gui_messages(user_id = None):
    if user_id is None:
        user_id = config.user_id
    path = config.config_dir + "/" + user_id + '/messages.mk'

    try:
        messages = eval(file(path).read())
    except IOError:
        messages = [] # Initialize list of messages

    # Delete too old messages
    updated = False
    for index, message in enumerate(messages):
        now = time.time()
        valid_till = message.get('valid_till')
        if valid_till is not None and valid_till < now:
            messages.pop(index)
            updated = True

    if updated:
        save_gui_messages(messages)

    return messages

def delete_gui_message(msg_id):
    messages = get_gui_messages()
    for index, msg in enumerate(messages):
        if msg['id'] == msg_id:
            messages.pop(index)
    save_gui_messages(messages)

def save_gui_messages(messages, user_id = None):
    if user_id is None:
        user_id = config.user_id
    path = config.config_dir + "/" + user_id + '/messages.mk'
    make_nagios_directory(os.path.dirname(path))
    file(path, 'w').write(repr(messages) + "\n")

loaded_with_language = False
def load_plugins():
    global loaded_with_language
    if loaded_with_language == current_language:
        return

    global g_message_path
    g_message_path = config.user_confdir + '/messages.mk'

    global notify_methods
    notify_methods = {
        'gui_popup': {
            'title':  _('Popup Message in the GUI (shows up alert window)'),
            'handler': notify_gui_msg,
        },
        'gui_hint': {
            'title':  _('Send hint to message inbox (bottom of sidebar)'),
            'handler': notify_gui_msg,
        },
        'mail': {
            'title':  _('Send an E-Mail'),
            'handler': notify_mail,
        },
    }

    dest_choices = [
        ('broadcast', _('Everybody (Broadcast)')),
        ('list', _('A list of specific users'), DualListChoice(
            choices = [ (uid, u.get('alias', uid)) for uid, u in config.multisite_users.items() ],
            allow_empty = False,
        )),
        #('contactgroup', _('All members of a contact group')),
    ]

    if config.save_user_access_times:
        dest_choices.append(('online', _('All online users')))

    global vs_notify
    vs_notify = [
        ('text', TextAreaUnicode(
            title = _('Text'),
            help = _('Insert the text to be sent to all reciepents.'),
            cols = 50,
            rows = 10
        )),
        ('dest', CascadingDropdown(
            title = _('Send notification to'),
            help = _('You can send the notification to a list of multiple users, which '
                     'can be choosen out of these predefined filters.'),
            choices = dest_choices,
        )),
        ('methods', ListChoice(
            title = _('How to notify'),
            choices = [ (k, v['title']) for k, v in notify_methods.items() ],
            default_value = ['popup'],
        )),
        ('valid_till', Optional(
            AbsoluteDate(
                include_time = True,
            ),
            title = _('Automatically invalidate notification'),
            label = _('Enable automatic invalidation at'),
            help = _('It is possible to automatically delete messages when the '
                     'configured time is reached. This makes it possible to inform '
                     'users about a scheduled event but suppress the notification '
                     'after the event has happened.'),
        )),
    ]

    config.declare_permission("general.notify",
         _("Notify Users"),
         _("This permissions allows users to send notifications to the users of "
           "the monitoring system using the web interface."),
         [ "admin" ])


def page_notify():
    if not config.may("general.notify"):
        raise MKAuthException(_("You are not allowed to use the notification module."))

    html.header(_('Notify Users'), stylesheets = ['pages', 'status', 'views'])

    html.begin_context_buttons()
    html.context_button(_('User Config'), 'wato.py?mode=users', 'users')
    html.end_context_buttons()

    def validate(msg):
        if not msg.get('text'):
            raise MKUserError('text', _('You need to provide a text.'))

        if not msg.get('methods'):
            raise MKUserError('methods', _('Please select at least one notification method.'))

        valid_methods = notify_methods.keys()
        for method in msg['methods']:
            if method not in valid_methods:
                raise MKUserError('methods', _('Invalid notitification method selected.'))

        # On manually entered list of users validate the names
        if type(msg['dest']) == tuple and msg['dest'][0] == 'list':
            existing = config.multisite_users.keys()
            for user_id in msg['dest'][1]:
                if user_id not in existing:
                    raise MKUserError('dest', _('A user with the id "%s" does not exist.') % user_id)

        # FIXME: More validation

    msg = forms.edit_dictionary(vs_notify, {},
        title = _('Notify Users'),
        buttontext = _('Send Notification'),
        validate = validate,
        method = 'POST',
    )

    if msg:
        msg['id']   = lib.gen_id()
        msg['time'] = time.time()

        # construct the list of recipients
        recipients = []

        if type(msg['dest']) == str:
            dest_what = msg['dest']
        else:
            dest_what = msg['dest'][0]

        if dest_what == 'broadcast':
            recipients = config.multisite_users.keys()

        elif dest_what == 'online':
            recipients = userdb.get_online_user_ids()

        elif dest_what == 'list':
            recipients = msg['dest'][1]

        num_recipients = len(recipients)
        num_success = 0
        num_failed  = 0

        # Now loop all notitification methods to send the notifications
        for user_id in recipients:
            for method in msg['methods']:
                try:
                    handler = notify_methods[method]['handler']
                    handler(user_id, msg)
                    num_success += 1
                except MKInternalError, e:
                    num_failed += 1
                    html.show_error(_('Failed to send %s notification to %s: %s') % (method, user_id, e))

        msg = _('The notification has been sent to %d of %d recipients.') % (num_success, num_recipients)
        msg += ' <a href="%s">%s</a>' % (html.makeuri([]), _('Back to previous page'))

        msg += '<p>Sent notification to: %s</p>' % ', '.join(recipients)

        html.message(msg)

    html.footer()

#   .--Notify Plugins------------------------------------------------------.
#   |    _   _       _   _  __         ____  _             _               |
#   |   | \ | | ___ | |_(_)/ _|_   _  |  _ \| |_   _  __ _(_)_ __  ___     |
#   |   |  \| |/ _ \| __| | |_| | | | | |_) | | | | |/ _` | | '_ \/ __|    |
#   |   | |\  | (_) | |_| |  _| |_| | |  __/| | |_| | (_| | | | | \__ \    |
#   |   |_| \_|\___/ \__|_|_|  \__, | |_|   |_|\__,_|\__, |_|_| |_|___/    |
#   |                          |___/                 |___/                 |
#   +----------------------------------------------------------------------+

def notify_gui_msg(user_id, msg):
    messages = get_gui_messages(user_id)
    if msg not in messages:
        messages.append(msg)
        save_gui_messages(messages, user_id)
    return True


def notify_mail(user_id, msg):
    import subprocess, time
    users = userdb.load_users(lock = False)
    user = users.get(user_id)

    if not user:
        raise MKInternalError(_('This user does not exist.'))

    if not user.get('email'):
        raise MKInternalError(_('This user has no mail address configured.'))

    recipient_name = user.get('alias')
    if not recipient_name:
        recipient_name = user_id

    sender_name = users[config.user_id].get('alias')
    if not sender_name:
        sender_name = user_id

    # Code mostly taken from notify_via_email() from notify.py module
    subject = _('Check_MK: Notification')
    body = _('''Greetings %s,

%s sent you a notification:

---
%s
---

''') % (recipient_name, sender_name, msg['text'])

    if msg['valid_till']:
        body += _('This notification has been created at %s and is valid till %s.') % (
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(msg['time'])),
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(msg['valid_till']))
        )

    # FIXME: Maybe use the configured mail command for Check_MK-Notify one day
    command = u"mail -s '$SUBJECT$' '$CONTACTEMAIL$'"
    command_utf8 = command.replace('$SUBJECT$', subject).replace('$CONTACTEMAIL$', user['email']).encode("utf-8")

    # Make sure that mail(x) is using UTF-8. Otherwise we cannot send notifications
    # with non-ASCII characters. Unfortunately we do not know whether C.UTF-8 is
    # available. If e.g. nail detects a non-Ascii character in the mail body and
    # the specified encoding is not available, it will silently not send the mail!
    # Our resultion in future: use /usr/sbin/sendmail directly.
    # Our resultion in the present: look with locale -a for an existing UTF encoding
    # and use that.
    for encoding in os.popen("locale -a 2>/dev/null"):
        l = encoding.lower()
        if "utf8" in l or "utf-8" in l or "utf.8" in l:
            encoding = encoding.strip()
            os.putenv("LANG", encoding)
            break
    else:
        raise MKInternalError(_('No UTF-8 encoding found in your locale -a! Please provide C.UTF-8 encoding.'))

    p = subprocess.Popen(command_utf8, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    stdout_txt, stderr_txt = p.communicate(body.encode("utf-8"))
    exitcode = p.returncode
    if exitcode != 0:
        raise MKInternalError(_('Mail could not be delivered. Exit code of command is %r') % exitcode)
    else:
        return True
