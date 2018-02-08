#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) 2018, Fabien Dupont <fdupont@redhat.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}


DOCUMENTATION = '''
module: manageiq_request_message
short_description: Update MIQ Request user message.
extends_documentation_fragment: manageiq
version_added: '2.4'
author: Fabien Dupont (@fdupont-redhat)
description:
  - The manageiq_request_message module supports updating user message for a request in ManageIQ.

options:
  request_id:
    description: The id of the request to update.
    required: true
  message:
    description: The message to apply to the request.
    required: true
'''

EXAMPLES = '''
- name: Update request message
  manageiq_request_message:
    request_id: 46000000000028
    message: Hello from Ansible
'''

RETURN = '''
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.manageiq import ManageIQ, manageiq_argument_spec

class ManageIQRequestMessage(object):
    """
        Object to execute request message operations in manageiq.
    """

    def __init__(self, manageiq):
        self.manageiq = manageiq

        self.module = self.manageiq.module
        self.api_url = self.manageiq.api_url
        self.client = self.manageiq.client

    def update(self, request_id, message):
        """ Update a MIQ Request user message.

        Returns:
            a short message describing the operation executed.
        """
        try:
            url = '%s/requests/%s' % (self.api_url, request_id)
            result = self.client.post(url, action='edit', options=dict(user_message=message))
        except Exception as e:
            self.module.fail_json(msg="failed to update user message for request %s: %s" % (request_id, str(e)))

        return dict(changed=True, msg=result['message'])

def main():
    # initialize arguments
    argument_spec = dict(
        request_id=dict(type='str', required=True),
        message=dict(type='str', required=True)
#        manageiq_connection=dict(type='dict', required=True)
    )
    # add the manageiq connection arguments to the arguments
    argument_spec.update(manageiq_argument_spec())

    module = AnsibleModule(argument_spec=argument_spec)

    request_id = module.params['request_id']
    message = module.params['message']

    manageiq = ManageIQ(module)
    manageiq_request_message = ManageIQRequestMessage(manageiq)

    res_args = manageiq_request_message.update(request_id, message)

    module.exit_json(**res_args)


if __name__ == "__main__":
    main()
