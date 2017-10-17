#!/usr/bin/python
# -*- coding: utf-8 -*-

from keystoneauth1.identity import v3
from keystoneauth1 import session
from NovaClient import NovaClient
from IPMIModule import IPMIManager
import time
import ConfigParser
import logging
import socket


class Operator(object):
	def __init__(self):
		# self.clusterList =
		self.nova_client = NovaClient.getInstance()
		self.ipmi_module=IPMIManager()
		config = ConfigParser.RawConfigParser()
		config.read('hass.conf')
		self.port = int(config.get("detection","polling_port"))


	def startNode(self,node_name, default_wait_time = 300):
		try:
			if self._checkNode(node_name):
				message = " node is in compute pool . The node is %s." % node_name
				self.ipmi_result=self.ipmi_module.startNode(node_name)
			else	:raise Exception

			if self.ipmi_result["code"]=="0":
				message+="start node success.The node is %s." %node_name
				logging.info(message)
				result = {"code": "0", "node_name": node_name, "message": message}
			else:raise Exception

			boot_up = self._check_node_boot_success(node_name,default_wait_time)
			if boot_up:
				return result
			else:raise Exception

		except Exception as e:

			message = " start node fail.The node is %s." % node_name
			logging.error(message)
			result = {"code": "1", "node_name": node_name, "message": message}
			return result

	def shutOffNode(self,node_name):
		if self._checkNode(node_name):
			self.ipmi_module.shutOffNode(node_name)
		else:
			pass


	def rebootNode(self,node_name):
		if self._checkNode(node_name):
			self.ipmi_module.rebootNode(node_name)
		else:
			pass

	def getAllInfoByNode(self,node_name):
		pass

	def getNodeInfoByType(self,node_name,sensor_type):
		pass

	def _checkNode(self,node_name):
		#is IPMI PC
		self.ipmistatus = self.ipmi_module._getIPMIStatus(node_name)
		if not self.ipmistatus:
			return False

		#is in computing pool
		if node_name in self.nova_client.getComputePool():
			message = " node is in compute pool . The node is %s." % node_name
			logging.info(message)
			return True
		else:
			message = " node is not in compute pool please check again! The node is %s." % node_name
			logging.error(message)
			return False

	def _check_node_boot_success(self, nodeName, check_timeout, timeout=1):
		status = False
		data = ""
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.setblocking(0)
		sock.settimeout(1)
		while "OK" not in data and check_timeout > 0:
			try:
				sock.sendto("polling request", (nodeName, int(self.port)))
				data, addr = sock.recvfrom(2048)
				if "OK" in data:
					status = True
				sock.close()
			except Exception as e:
				print e
			finally:
				time.sleep(1)
				check_timeout -= 1
		return status


def main():
	pass


if __name__ == '__main__':
	main()