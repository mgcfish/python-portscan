# User Defined Modules
from . import htmlgenerator
from . import log
from . import scanobject
from . import upload

# Standard Library Modules
import os

from libnmap.process import NmapProcess
from libnmap.parser import NmapParser
from queue import Queue
from threading import Thread

__all__ = [
    'BusinessUnit'
]


class NmapWorker(Thread):
    def __init__(self, queue):
        Thread.__init__(self)
        self.queue = queue

    def run(self):
        while True:
            # Get the work from the queue and expand the tuple
            target, options = self.queue.get()
            nmap_proc = NmapProcess(targets=target, options=options, safe_mode=False)
            log.send_log(nmap_proc.get_command_line())
            nmap_proc.run()
            self.queue.task_done()


# Business Uni
class BusinessUnit:
    def __init__(self, p_name, p_path, p_verbose="", p_org=""):
        """ BusinessUnit Class Constructor.

        :ivar businessUnit: (string) Description: BusinessUnit name
        :ivar path: (string) Description: Path to top-level config directory
        :ivar verbose: (string) Description: Verbose information provided to BusinessUnit
        :ivar org: (string) Description: Organization the BusinessUnit belongs to
        :ivar machineCount: (int) Description: The number of unique hosts being scanned
        :ivar emails: (list) Description: List of emails read from the {}.conf file
        :ivar stats: (dict) Dictionary of stats generated by the scan
        :ivar outfile: (string) Description: Path to generated report
        """

        isinstance(p_name, str)
        isinstance(p_path, str)
        isinstance(p_verbose, str)
        isinstance(p_org, str)

        log.send_log("Scan started on " + p_name)

        # Provided input population
        self.business_unit = p_name
        self.path = p_path
        self.verbose = p_verbose
        self.org = p_org

        # Object populates this when Reading configs
        self.machine_count = 0;
        self.live_host = 0
        self.exclude_string = ""
        self.sets = []
        self.emails = self.mobile = self.links = []
        self.scan_objs = []
        self.stats = {"open": 0, "open|filtered": 0, "filtered": 0, "closed|filtered": 0, "closed": 0}

        # internal variables
        self.ports_bool = True

        # immediately populated by checkDeps()
        self.config_dir = self.ports_file = self.ip_file = self.nmap_dir = self.ports = self.outfile = ""
        self.CheckDeps()

    # Check that all necessary configuration dependencies exist
    def CheckDeps(self):
        """ Private Method that depends on self.path existing in the object. """
        if self.path == "":
            log.send_log(
                "CheckDeps called on " + self.business_unit + " object but does not contain a self.path defined variable. ")
            exit(0)

        self.config_dir = self.path + "config/"
        if not self.CheckExist(self.config_dir):
            exit(0)

        self.ports_file = self.config_dir + "ports_bad_" + self.business_unit
        if not self.CheckExist(self.ports_file):
            print("No ports_bad_" + self.business_unit + " specified, continuing without.")
            self.ports_bool = False

        self.ip_file = self.config_dir + "ports_baseline_" + self.business_unit + ".conf"
        if not self.CheckExist(self.ip_file):
            exit(0)

        # output directory
        self.nmap_dir = self.path + "nmap-" + self.business_unit + "/"
        if not self.CheckExist(self.nmap_dir):
            log.send_log(self.nmap_dir + " does not exist... creating now")
            os.system("mkdir " + self.nmap_dir)

    def CheckExist(self, file):
        isinstance(file, str)
        """ Helper private method for CheckDeps """
        if not os.path.exists(file):
            print(file + " does not exist. Exiting...")
            log.send_log(file + " does not exist.")
            return False
        else:
            return True

    def ReadPorts(self):
        """ Parse and store general ports from ports_bad_{business_unit}."""

        # In case a user didn't specify a ports_bad file, but called this anyway
        if not self.ports_bool:
            return

        try:
            with open(self.ports_file, 'r') as f:
                for line in f:

                    # Comment removal
                    if line[0] == '#':
                        continue
                    elif '#' in line:
                        line = line.split('#')[0]

                    self.ports = self.ports + line.strip(' \t\n\r')

                    # trim any trailing commas and add ONLY one
                    # IMPORTANT. DO NOT REMOVE; SANITIZES USER INPUT
                    while self.ports[-1] == ',':
                        self.ports = self.ports[:-1]
                    self.ports = self.ports + ','

        except IOError:
            log.send_log("Unable to open " + self.ports_file)
            exit(1)
        log.send_log("Finished reading ports")

    def ReadBase(self):
        """ Parse and store networks, subnets, ranges, and individual IP's for scanning from
        ports_baseline_{business_unit}.conf. """
        try:
            with open(self.ip_file, 'r') as f:
                for line in f:
                    # test if line is empty and continue is so
                    try:
                        line.strip(' \t\n\r')[0]
                    except:
                        continue

                    # Comments and emails
                    if line[0] == '#':
                        continue
                    elif '#' in line:
                        line = line.split('#')[0]
                    elif '@' in line:
                        if "-m" in line:
                            self.mobile.append(line.split(' ')[0].strip(' \t\n\r'))
                        else:
                            self.emails.append(line.strip(' \t\n\r'))
                        continue

                    # Business unit scan object
                    if line[0] == "-":
                        self.exclude_string = self.exclude_string + line[1:].strip(' \t\n\r') + ","
                        continue
                    else:
                        # create scan object
                        self.sets.append(line.strip(' \t\r\n'))
                        if self.ports_bool == False and ':' in self.line:
                            self.ports_bool = True

        except IOError:
            log.send_log("Unable to open " + self.ip_file)
            exit(1)
        log.send_log("Finished reading Commands")

    def Scan(self):
        """Execute scanning commands held in ScanObjects. Uses forking and waits on PID returns."""
        if self.ports_bool == False:
            log.send_log("No ports specified for scanning")
            exit(0)

        for item in self.sets:
            BU_SO = scanobject.ScanObject()
            # populate fields based on line input
            BU_SO.CreateCommand(item, self.exclude_string, self.ports, self.nmap_dir)
            self.scan_objs.append(BU_SO)
            self.machine_count = self.machine_count + BU_SO.GetMachineCount()

        queue = Queue()
        # Run several threads to be more time efficient
        for x in range(4):
            worker = NmapWorker(queue)
            worker.daemon = True
            worker.start()
        for obj in self.scan_objs:
            queue.put((obj.command['target'], obj.command['options']))
        queue.join()

    def ParseOutput(self, business_path=""):
        """Parse and assemble human readable csv report of all nmap results. """
        if len(business_path) > 0:
            master_dict = {}
            with open(business_path, "r") as f:
                for line in f:
                    test = line.strip(' \n\t\r')
                    test = test.split(',')
                    master_dict[test[1]] = test[0]
            f.close()

        master_out = []

        backup = {}

        try:
            with open(self.nmap_dir + "output-" + self.business_unit + ".bak") as f:
                for line in f:
                    line = line.split(',')
                    if line[0] not in backup:
                        backup[line[0]] = [line[1]]
                    else:
                        backup[line[0]].append(line[1])
            f.close()
        except IOError:
            pass

        for obj in self.scan_objs:
            nmap_report = NmapParser.parse_fromfile(obj.outfile)
            for scanned_hosts in nmap_report.hosts:
                if scanned_hosts.is_up():
                    self.live_host = self.live_host + 1
                for port in scanned_hosts.get_ports():
                    nmap_obj = scanned_hosts.get_service(port[0], "tcp")
                    if nmap_obj.state == "open":
                        out = [scanned_hosts.address, str(nmap_obj.port), nmap_obj.state, nmap_obj.service]

                        # append business type
                        if len(business_path) > 0:
                            out.append(master_dict.get(scanned_hosts.address, "") + "")
                        else:
                            out.append("")

                        # append new or not
                        if len(backup) > 0:
                            if scanned_hosts.address in backup and str(nmap_obj.port) in backup[scanned_hosts.address]:
                                out.append("*")
                            else:
                                out.append("")
                        else:
                            out.append("*")

                        master_out.append(",".join(out))

                        self.stats[nmap_obj.state] = self.stats[nmap_obj.state] + 1
                    else:
                        self.stats[nmap_obj.state] = self.stats[nmap_obj.state] + 1
            log.send_log("File " + obj.outfile + " parsed.")
        return master_out

    def Collect(self, business_path=""):
        """ Calls ParseOutput to collect all output into a readable csv.
        Generates HTML Generation and Uploading to DropBox. """
        isinstance(business_path, str)

        out = self.ParseOutput(business_path)
        self.outfile = self.nmap_dir + "output-" + self.business_unit + ".csv";

        try:
            os.system("cp " + self.outfile + " " + self.nmap_dir + "output-" + self.business_unit + ".bak")
            print("Successfully copied backup")
        except:
            print("Unsuccessfully copied backup")

        with open(self.outfile, 'w') as f:
            for line in out:
                f.write(line + "\n")

        log.send_log("Generated CSV report.")
        # upload Report to DropBox
        try:
            self.links = upload.UploadToDropbox([self.outfile],
                                                '/' + os.path.basename(os.path.normpath(self.nmap_dir)) + '/')
        except EnvironmentError:
            self.links = []
        # Generate HMTL
        htmlgenerator.GenerateHTML(self)
