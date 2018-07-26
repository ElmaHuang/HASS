#########################################################
#:Date: 2017/12/13
#:Version: 1
#:Authors:
#    - Elma Huang <huanghuei0206@gmail.com>
#    - LSC <sclee@g.ncu.edu.tw>
#:Python_Version: 2.7
#:Platform: Unix
#:Description:
#   This is a class maintains recovery methods.
##########################################################

from ClusterManager import ClusterManager
from NovaClient import NovaClient
from Detector import Detector
from Response import Response
import FailureType
import logging
import ConfigParser
import time
import subprocess
import datetime
from RESTClient import RESTClient
from III import III


class RecoveryManager(object):
    def __init__(self):
        self.nova_client = NovaClient.getInstance()
        self.config = ConfigParser.RawConfigParser()
        self.config.read('/etc/hass.conf')
        self.recover_function = {FailureType.NETWORK_FAIL: self.recoverNetworkIsolation,
                                 FailureType.SERVICE_FAIL: self.recoverServiceFail,
                                 FailureType.POWER_FAIL: self.recoverPowerOff,
                                 FailureType.SENSOR_FAIL: self.recoverSensorCritical,
                                 FailureType.OS_FAIL: self.recoverOSHanged}
        self.rest_client = RESTClient.getInstance()

        self.iii_support = self.config.getboolean("iii", "iii_support")
        self.iii = III()

    def recover(self, fail_type, cluster_id, fail_node_name):
        return self.recover_function[fail_type](cluster_id, fail_node_name)

    def recoverOSHanged(self, cluster_id, fail_node_name):
        cluster = ClusterManager.getCluster(cluster_id)
        if not cluster:
            logging.error("RecoverManager : cluster not found")
            return
        fail_node = cluster.getNodeByName(fail_node_name)
        print "fail node is %s" % fail_node.name
        print "start recovery vm"
        self.recoverVM(cluster, fail_node)
        print "end recovery vm"
        return self.recoverNodeByReboot(fail_node)

    def recoverPowerOff(self, cluster_id, fail_node_name):
        cluster = ClusterManager.getCluster(cluster_id)
        if not cluster:
            logging.error("RecoverManager : cluster not found")
            return
        fail_node = cluster.getNodeByName(fail_node_name)
        print "fail node is %s" % fail_node.name
        print "start recovery vm"
        self.recoverVM(cluster, fail_node)
        print "end recovery vm"
        return self.recoverNodeByStart(fail_node)

    def recoverNodeCrash(self, cluster_id, fail_node_name):
        cluster = ClusterManager.getCluster(cluster_id)
        if not cluster:
            logging.error("RecoverManager : cluster not found")
            return
        fail_node = cluster.getNodeByName(fail_node_name)
        print "fail node is %s" % fail_node.name
        print "start recovery vm"
        self.recoverVM(cluster, fail_node)
        print "end recovery vm"
        return self.recoverNodeByShutoff(fail_node)

    def recoverNetworkIsolation(self, cluster_id, fail_node_name):
        cluster = ClusterManager.getCluster(cluster_id)
        if not cluster:
            logging.error("RecoverManager : cluster not found")
            return
        fail_node = cluster.getNodeByName(fail_node_name)

        network_transient_time = int(self.config.get("default", "network_transient_time"))
        second_chance = FailureType.HEALTH
        while network_transient_time > 0:
            try:
                subprocess.check_output(['timeout', '0.2', 'ping', '-c', '1', fail_node.name],
                                               stderr=subprocess.STDOUT, universal_newlines=True)
                second_chance = FailureType.HEALTH
                break
            except subprocess.CalledProcessError:
                print "network unreachable for %s" % fail_node_name
                network_transient_time -= 1
                time.sleep(1)
                second_chance = FailureType.NETWORK_FAIL
        if second_chance == FailureType.HEALTH:
            print "The network status of %s return to health" % fail_node.name
            return True
        else:
            print "after 30 seconds, network still unreachable, start recovery."
            print "fail node is %s" % fail_node.name
            print "start recovery vm"
            self.recoverVM(cluster, fail_node)
            print "end recovery vm"
            return self.recoverNodeByReboot(fail_node)

    def recoverSensorCritical(self, cluster_id, fail_node_name):
        cluster = ClusterManager.getCluster(cluster_id)
        if not cluster:
            logging.error("RecoverManager : cluster not found")
            return
        fail_node = cluster.getNodeByName(fail_node_name)
        print "fail node is %s" % fail_node.name
        print "start recovery vm"
        self.recoverVM(cluster, fail_node)
        print "end recovery vm"
        return self.recoverNodeByShutoff(fail_node)

    def recoverServiceFail(self, cluster_id, fail_node_name):
        cluster = ClusterManager.getCluster(cluster_id)
        if not cluster:
            logging.error("RecoverManager : cluster not found")
            return
        fail_node = cluster.getNodeByName(fail_node_name)

        port = int(self.config.get("detection", "polling_port"))
        os_version = self.config.get("version", "os_version")
        detector = Detector(fail_node, port)
        fail_services = detector.getFailServices()

        if fail_services == None:
            logging.info("get fail service equals to None, abort recover service fail")
            return True

        status = True
        if "agents" in fail_services:
            status = self.restartDetectionService(fail_node)
        else:
            status = self.restartServices(fail_node, fail_services, os_version)

        if not status:  # restart service fail
            fail_services = fail_services.replace(";","")
            return self.iii.send_recover_service_failed(fail_node, fail_services)
        else:
            return status  # restart service success

    def recoverVM(self, cluster, fail_node):
        if len(cluster.getNodeList()) < 2:
            logging.error("RecoverManager : evacuate fail, cluster only one node")
            return
        if not fail_node:
            logging.error("RecoverManager : not found the fail node")
            return
        target_host = cluster.findTargetHost(fail_node)
        print "target_host : %s" % target_host.name
        if not target_host:
            logging.error("RecoverManager : not found the target_host %s" % target_host)

        protected_instance_list = cluster.getProtectedInstanceListByNode(fail_node)
        print "protected list : %s" % protected_instance_list
        for instance in protected_instance_list:
            try:
                if target_host.instanceOverlappingInLibvirt(instance):
                    logging.info("instance %s overlapping in %s" % (instance.name, target_host.name))
                    logging.info("start undefine instance in %s" % target_host.name)
                    print "instance %s overlapping in %s" % (instance.name, target_host.name)
                    print "start undefine instance in %s" % target_host.name
                    target_host.undefineInstance(instance)
                    print "end undefine instance"
            except Exception as e:
                logging.error("instance overlapping in libvirt exception")
                logging.error(str(e))
                logging.info("undefineInstance second chance via socket")
                try:
                    target_host.undefine_instance_via_socket(instance)
                except Exception as e:
                    logging.error("undefine instance sencond chance fail %s" % str(e))
                    pass
            try:
                print "start evacuate"
                logging.info("start evacuate")
                cluster.evacuate(instance, target_host, fail_node)
            except Exception as e:
                print str(e)
                logging.error(str(e))
                logging.error("RecoverManager - The instance %s evacuate failed" % instance.id)

        # print "check instance status"
        # status = self.checkInstanceNetworkStatus(fail_node, cluster)
        # if status == False:
        #     logging.error("RecoverManager : check vm status false")

        print "update instance"
        logging.info("update instance")
        cluster.updateInstance()

        if self.iii_support:
            self.iii.update_iii_database(protected_instance_list, target_host, fail_node)
            

    def recoverNodeByReboot(self, fail_node):
        print "start recover node by reboot"
        prev = datetime.datetime.now()
        result = fail_node.reboot()
        print "boot node result : %s" % result.message
        message = "RecoveryManager recover "
        if result.code == "succeed":
            logging.info(message + result.message)
            boot_up = self.checkNodeBootSuccess(fail_node)
            if boot_up:
                end = datetime.datetime.now()
                print "host recovery time : %s" % (end - prev)
                print "Node %s recovery finished." % fail_node.name
                return True
            else:
                logging.error(message + "Can not reboot node %s successfully", fail_node.name)
                return False
        else:
            logging.error(message + result.message)
            return False

    def recoverNodeByShutoff(self, fail_node):
        print "start recover node by shutoff"
        result = fail_node.shutoff()
        if result.code == "succeed":
            return False  # shutoff need to remove from cluster, so return False
        else:
            logging.error(result.message)
            print result.message

    def recoverNodeByStart(self, fail_node):
        print "start recover node by start"
        prev = datetime.datetime.now()
        result = fail_node.start()
        print "boot node result : %s" % result.message
        message = "RecoveryManager recover"
        if result.code == "succeed":
            logging.info(message + result.message)
            boot_up = self.checkNodeBootSuccess(fail_node)
            if boot_up:
                end = datetime.datetime.now()
                print "host recovery time : %s" % (end - prev)
                print "Node %s recovery finished." % fail_node.name
                return True
            else:
                logging.error(message + "Can not start node %s successfully", fail_node.name)
                return False
        else:
            logging.error(message + result.message)
            return False

    def restartDetectionService(self, fail_node):
        print "Start service failure recovery by starting Detection Agent"
        agent_path = self.config.get("path", "agent_path")
        cmd = "service Detectionagentd restart"
        print cmd
        try:
            fail_node.remote_exec(cmd)  # restart DetectionAgent service
            time.sleep(5)

            cmd = "ps aux | grep '[D]etectionAgent.py'"
            stdin, stdout, stderr = fail_node.remote_exec(cmd)
            service = stdout.read()
            print service
            if "python DetectionAgent.py" in service:  # check DetectionAgent
                return True
            return False
        except Exception as e:
            print str(e)
            return False

    def restartServices(self, fail_node, fail_services, os_version, check_timeout=60):
        service_mapping = {"libvirt": "libvirt-bin", "nova": "nova-compute", "qemukvm": "qemu-kvm"}
        fail_service_list = fail_services.split(":")[-1].split(";")[0:-1]

        try:
            for fail_service in fail_service_list:
                fail_service = service_mapping[fail_service]
                if os_version == "16":
                    cmd = "systemctl restart %s" % fail_service
                else:
                    cmd = "sudo service %s restart" % fail_service
                print cmd
                stdin, stdout, stderr = fail_node.remote_exec(cmd)  # restart service

                while check_timeout > 0:
                    if os_version == "16":
                        cmd = "systemctl status %s | grep active" % fail_service
                    else:
                        cmd = "service %s status" % fail_service
                    stdin, stdout, stderr = fail_node.remote_exec(cmd)  # check service active or not

                    if not stdout.read():
                        print "The node %s service %s still doesn't work" % (fail_node.name, fail_service)
                    else:
                        print "The node %s service %s successfully restart" % (fail_node.name, fail_service)
                        return True  # recover all the fail service
                    time.sleep(1)
                    check_timeout -= 1
                return False
        except Exception as e:
            print str(e)
            return False

    def checkInstanceNetworkStatus(self, fail_node, cluster, check_timeout=60):
        status = False
        fail = False
        protected_instance_list = cluster.getProtectedInstanceListByNode(fail_node)
        for instance in protected_instance_list:
            try:
                status = self._pingInstance(instance.getIP("ext-net"), check_timeout)
            except Exception as e:
                print "vm : %s has no floating network, abort ping process!" % instance.name
                continue
            if not status:
                fail = True
                logging.error("vm %s cannot ping %s" % (instance.name, instance.getIP("ext-net")))
        return fail

    def _pingInstance(self, ip, check_timeout):
        status = False
        time.sleep(5)
        while check_timeout > 0:
            try:
                print "check vm %s" % ip
                response = subprocess.check_output(['timeout', '0.2', 'ping', '-c', '1', ip], stderr=subprocess.STDOUT,
                                                   universal_newlines=True)
                status = True
                break
            except subprocess.CalledProcessError:
                status = False
            finally:
                time.sleep(1)
                check_timeout -= 1
        return status

    def checkNodeBootSuccess(self, node, check_timeout=300):
        port = int(self.config.get("detection", "polling_port"))
        detector = Detector(node, port)
        print "waiting node to reboot"
        time.sleep(5)
        print "start check node booting"
        while check_timeout > 0:
            try:
                if detector.checkServiceStatus() == FailureType.HEALTH:
                    return True
            except Exception as e:
                print str(e)
            finally:
                time.sleep(1)
                check_timeout -= 1
        return False


if __name__ == "__main__":
    pass
    # r = RecoveryManager()
    # l = r.remote_exec("compute3","virsh list --all")
