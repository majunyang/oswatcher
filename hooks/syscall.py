# sys
import json
import re
from io import StringIO

# local
from oswatcher.model import SyscallTable, Syscall

# 3rd
from see import Hook


class SyscallTableHook(Hook):

    TABLE_NAMES = {
        0: 'nt',
        1: 'win32k'
    }

    def __init__(self, parameters):
        super().__init__(parameters)
        # config
        self.graph = self.configuration['graph']
        self.context.subscribe('rekall_session', self.extract_syscall_table)

    def extract_syscall_table(self, event):
        self.logger.info('Extracting the syscall table')
        s = event.session
        output = StringIO()
        self.logger.debug('Running Rekall SSDT plugin')
        s.RunPlugin("ssdt", output=output)
        sdt = self.parse_ssdt_output(output)
        self.insert_db(sdt)

    def parse_ssdt_output(self, output):
        sdt = []
        ssdt = json.loads(output.getvalue())
        for e in ssdt:
            e_type = e[0]
            if e_type == 'r':
                e_data = e[1]
                if e_data['divider'] is not None:
                    # new table
                    m = re.match(r'Table (?P<table_index>[0-9]) @ .*', e[1]["divider"])
                    index = int(m.group('table_index'))
                    self.logger.debug("New syscall table - %d", index)
                    syscall_table = (index, [])
                    sdt.append(syscall_table)
                else:
                    index = e_data["entry"]
                    m = re.match(r'(?P<table>.+)!(?P<name>.+)', e_data["symbol"]["symbol"])
                    name = m.group('name')
                    address = hex(e_data["target"])
                    rest, last_ssdt = sdt[-1]
                    syscall_entry = (index, name, address)
                    self.logger.debug("Inserting syscall entry %s", syscall_entry)
                    last_ssdt.append(syscall_entry)
        return sdt

    def insert_db(self, sdt):
        self.logger.info('Inserting syscall table into database')
        systable_node_list = []
        for table_index, table in sdt:
            systable_node = SyscallTable(table_index, self.TABLE_NAMES[table_index])
            for index, name, address in table:
                syscall_node = Syscall(index, name, address)
                systable_node.syscalls.add(syscall_node)
                syscall_node.owned_by.add(systable_node)
                self.graph.push(syscall_node)

            self.graph.push(systable_node)
            systable_node_list.append(systable_node)
        # signal the operating system Hook that the syscalls has been
        # inserted, to add the relationship
        self.context.trigger('syscalls_inserted', tables=systable_node_list)
