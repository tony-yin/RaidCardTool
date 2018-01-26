import do_shell
from copy import deepcopy

MEGACLI = '/opt/MegaRAID/MegaCli/MegaCli64'

class MegaraidTool():

    def get_disk_type(self, disk_name):
        scsi_info = do_shell("lsscsi | grep {} -w".format(disk_name))
        target_id = scsi_info.split()[0].split(":")[2]
        serial_nu = scsi_info.split()[3].strip()[2:]
        if "LSI" in scsi_info:
            disk_type = self.get_ld_type(target_id, serial_nu)
        else:
            disk_type = self.get_pd_type(target_id)
        return disk_type

    def get_ld_type(self, target_id, serial_nu):
        disk_type = ''
        cmd = MEGACLI + ' cfgdsply -aALL -NoLog|grep -E "Product Name|Target Id|Media Type"'
        output = do_shell(cmd)
        adapters = output.split('Product Name')
        for adapter in adapters:
            if serial_nu not in adapter:
                continue
            lines = adapter.split('\n')
            for line in lines:
                if "Target Id: {}".format(target_id) in line:
                    index = lines.index(line)
                    if 'Solid State Device' in lines[index + 1]:
                        disk_type = "SSD"
                    else :
                        disk_type = "HDD"
                    break
            if disk_type != '':
                break
        return disk_type

    def get_pd_type(self, target_id):
        disk_type = ''
        cmd = MEGACLI + ' pdlist aAll | grep -E "Device Id|Media Type"'
        output = do_shell(cmd)
        lines = output.split('\n')
        if 'Device Id: {}'.format(target_id) not in lines:
            return ''
        index = lines.index('Device Id: {}'.format(target_id))
        if 'Solid State Device' in lines[index + 1]:
            disk_type = "SSD"
        else :
            disk_type = "HDD"
        return disk_type

    def get_specific_disk_type(self, media_type):
        if 'Solid' in media_type:
            disk_type = 'SSD'
        else:
            disk_type = 'HDD'

        return disk_type

    def check_disk_is_ssd(self, disk_name):
        disk_type = self.get_disk_type(disk_name)
        if disk_type == 'SSD':
            return True
        else:
            return False

    def get_ssd_health(self, disk_name):
        scsi_info = do_shell("lsscsi | grep {} -w".format(disk_name))
        target_id = scsi_info.split()[0].split(":")[2]
        if "LSI" in scsi_info:
            cmd = MEGACLI + ' ldpdinfo aAll | grep -E "Target Id|Device Id"'
            output = do_shell(cmd)
            lines = output.splitlines()
            for line in lines:
                if 'Target Id: {}'.format(target_id) in line:
                    index = lines.index(line)
                    target_id = lines[index + 1].split(':')[-1].strip()
                    break

        lifetime = ''
        try:
            cmd= "smartctl -a -d megaraid,{} {}|grep 'Media_Wearout_Indicator'".format(target_id, disk_name)
            media_health = do_shell(cmd).split()[4]
            if media_health != '':
                lifetime = '{}%'.format(int(media_health))
        except Exception as e:
            logger.error("cannot get ssd health: %s", str(e))

        return lifetime

    def get_disk_group_info(self):
        cmd = MEGACLI + "CfgDsply -A0 |grep -Ei  " \
              " 'Disk Group|Enclosure Device|Slot Number'"
        info = do_shell(cmd).split('\n')

        return info

    def delete_hotspare_disk(self, enclosure, slot):
        cmd = MEGACLI + " PDHSP -Rmv -PhysDrv [{}:{}] -A0".format(enclosure, slot)
        do_shell(cmd)

    def create_hotspare_disk(self, enclosure, slot):
        cmd = MEGACLI + "PDHSP -Set PhysDrv [{}:{}] -A0".format(enclosure, slot)
        do_shell(cmd)

    def create_raid(self, level, disks, strip_size):
        cmd = MEGACLI + " CfgLdAdd -r{} {} -strpsz{} -A0".format(level, disks, strip_size)
        do_shell(cmd)

class HBATool():

    KeyMap = {
       'Enclosure #': 'Enclosure Device ID',
       'Slot #': 'Slot Number',
       'Drive Type': 'Media Type',
       'State': 'Firmware state',
       'Initiator at ID #': 'Disk Group: '
    }

    StateMap = {
        'Failed (FLD)': 'Offline',
        'Rebuilding (RBLD)': 'Rebuild',
        'Hot Spare (HSP)': 'Hotspare'
    }

    def get_disk_type(self, disk_name):
        scsi_info = do_shell("lsscsi | grep {} -w".format(disk_name))
        if "LSI" in scsi_info:
            target_id = scsi_info.split()[0].split(":")[2]
            disk_type = self.get_ld_type(target_id)
        else:
            sas_address = do_shell('udevadm info --query=symlink --name={}'.format(disk_name))
            disk_type = self.get_pd_type(sas_address)
        return disk_type

    def get_ld_type(self, target_id):
        disk_type = ''
        controllers = self.get_controllers()
        for controller in controllers:
            cmd = 'sas3ircu {} display|grep -E "Initiator at ID|Drive Type"'.format(controller)
            output = do_shell(cmd)
            if 'Initiator at ID #{}'.format(target_id) in output:
                lines = output.splitlines()
                index = lines.index('Initiator at ID #{}'.format(target_id))
                if 'HDD' in lines[index + 1]:
                    disk_type = 'HDD'
                else:
                    disk_type = 'SSD'
                break
        return disk_type

    def get_pd_type(self, sas_address):
        disk_type = ''
        controllers = self.get_controllers()
        for controller in controllers:
            cmd = 'sas3ircu {} display|grep -E "SAS Address|Drive Type"'.format(controller)
            output = do_shell(cmd)
            lines = output.splitlines()
            for i in xrange(0, len(lines), 2):
                address = lines[i].split()[-1].replace('-', '')
                if address in sas_address:
                    if 'HDD' in lines[i + 1]:
                        disk_type = 'HDD'
                    else:
                        disk_type = 'SSD'
                    break
            if disk_type != '':
                break
        return disk_type

    def get_controllers(self):
        cmd = 'sas3ircu list | awk \'{print $1}\''
        list = do_shell(cmd).splitlines()
        index = list.index('Index') + 2
        controllers = []
        for i in range(index, len(list) - 1):
            controllers.append(list[i])
        return controllers

    def get_specific_disk_type(self, media_type):
        if 'SSD' in media_type:
            disk_type = 'SSD'
        else:
            disk_type = 'HDD'

        return disk_type


    def check_disk_is_ssd(self, disk_name):
        disk_type = self.get_disk_type(disk_name)
        if disk_type == 'SSD':
            return True
        else:
            return False

    def get_ssd_health(self, disk_name):
        return ''

    def get_disk_group_info(self):
        info = []
        cmd = 'sas3ircu 0 display|grep -wE "Initiator at ID #|Enclosure #|Slot #"'
        output = do_shell(cmd)
        for k,v in self.KeyMap.iteritems():
            if k in output:
                output = output.replace(k, v)
        info += output.splitlines()

        return info

    def delete_hotspare_disk(self, enclosure, slot):
        cmd = 'sas3ircu 0 hotspare delete {}:{}'.format(enclosure, slot)
        do_shell(cmd)

    def create_hotspare_disk(self, enclosure, slot):
        cmd = 'sas3ircu 0 hotspare {}:{}'.format(enclosure, slot)
        do_shell(cmd)

    def create_raid(self, level, disks, strip_size):
        disks = disks[1:-1].replace(',', ' ')
        cmd = 'sas3ircu 0 create raid {} max {} noprompt'.format(level, disks)
        do_shell(cmd)

class NotSupport():

    def get_disk_type(self, disk_name):
        return ''

    def check_disk_is_ssd(self, disk_name):
        return False

    def get_ssd_health(self, disk_name):
        return ''

    def get_disk_group_info(self):
        return []

    def delete_hotspare_disk(self, enclosure, slot):
        pass

    def create_hotspare_disk(self, enclosure, slot):
        pass

    def create_raid(self, level, disks, strip_size):
        pass

class RaidCardToolFactory():

    RaidCardMap = {
        'SAS2208': MegaraidTool,
        'SAS3008': HBATool,
        'NotSupport': NotSupport
    }

    def getTool(self):
        card_model = self.get_raidcard_model()
        tool = self.RaidCardMap[card_model]()
        return tool

    def get_raidcard_model(self):
        card_model = 'NotSupport'
        card_info = do_shell("lspci | grep 'LSI Logic'")
        if card_info == '':
            return card_model
        card = card_info.strip().splitlines()[0].split()
        if 'RAID bus controller' in card_info:
            card_model = card[10] + card[11]
        elif 'Attached SCSI controller' in card_info:
            card_model = card[10]
        return card_model
