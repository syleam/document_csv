# -*- coding: utf-8 -*-
##############################################################################
#
#    document_csv module for OpenERP
#    Copyright (C) 2009 SYLEAM (<http://www.syleam.fr>) Christophe CHAUVET
#
#    This file is a part of document_csv
#
#    document_csv is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    document_csv is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from osv import osv
from osv import fields
from tools.translate import _
from tools import ustr
import netsvc
import time
import pooler

_encoding = [
    ('utf-8', 'UTF 8'),
    ('cp850', 'CP 850 IBM'),
    ('iso8859-1','Latin 1'),
    ('iso8859-15','Latin 9'),
]

class import_list(osv.osv):
    _name='document.import.list'
    _description = 'Document importation list'

    _columns = {
        'name': fields.char('Import name', size=128, required=True),
        'model_id': fields.many2one('ir.model','Model', required=True),
        'ctx': fields.char('Context', size=256, help='this part complete the original context'),
        'disable': fields.boolean('Disable', help='Check this, if you want to disable it'),
        'err_mail': fields.boolean('Send log by mail', help='The log file was send to all users of the groupes'),
        'err_reject': fields.boolean('Reject all if error', help='Reject all lines if there is an error'),
        'group_id': fields.many2one('res.groups', 'Group', help='Group use for sending email'),
        'csv_sep': fields.char('Separator', size=1, required=True),
        'csv_esc': fields.char('Escape', size=1),
        'encoding': fields.selection(_encoding, 'Encoding'),
        'line_ids': fields.one2many('document.import.list.line','list_id', 'Lines'),
        'directory_id': fields.many2one('document.directory','Directory', required=True, help='Select directory where the file was put'),
        'backup_filename': fields.char('Backup filename', size=128, required=True, help='Indique the name of the file to backup, see legend at bottom'),
        'backup_dir_id': fields.many2one('document.directory', 'Backup directory', required=True, help='Select directory where the backup file was put'),
        'reject_filename': fields.char('Reject filename', size=128, required=True, help='Indique the name of the reject file, see legend at bottom'),
        'reject_dir_id': fields.many2one('document.directory', 'Reject directory', required=True, help='Select the directory wher the reject file was put'),
        'log_filename': fields.char('Log filename', size=128, required=True, help='Indique the name of the log file, see legend at bottom'),
        'log_dir_id': fields.many2one('document.directory', 'Log directory', required=True, help='Select directory where the backup file was put'),
        'backup': fields.boolean('Store the backup', help='If check, the original file is backup, before remove from the directory'),
        'mail_cc': fields.char('CC', size=128, help='Add cc mail, separate by comma'),
        'mail_body': fields.text('Body'),
    }

    _defaults = {
        'ctx': lambda *a: '{}',
        'disable': lambda *a: True,
        'csv_sep': lambda *a: ';',
        'csv_esc': lambda *a: '"',
        'backup_filename': lambda *a: 'sample-%Y%m%d_%H%M%S.csv',
        'reject_filename': lambda *a: 'sample-%Y%m%d_%H%M%S.rej',
        'log_filename': lambda *a: 'sample-%Y%m%d_%H%M%S.log',
    }

    def onchange_context(self, cr, uid, ids, val, context=None):
        if not context: context = {}
        warning = {}
        warning['title'] = _('Error')
        warning['message'] = _('Bad context value')
        if ids and not val == '{}':
            try:
                val = eval(val)
                if not isinstance(val, dict):
                    return {'warning': warning}
            except SyntaxError, e:
                warning['message'] = _('Syntax error\n* %r') % e
                return {'warning': warning}
            except TypeError, e:
                warning['message'] = _('The context must be start with { and ending with }\n* %r') % e
                return {'warning': warning}

        return {'warning': False}

import_list()

class import_list_line(osv.osv):
    """
    Describe each columns from the CSV file and affect to a field in object
    - 
    """
    _name='document.import.list.line'
    _description='Document importation list line'

    _columns = {
        'list_id': fields.many2one('document.import.list', 'Line', required=True),
        'name': fields.char('Field name', size=128, required=True),
        'field_id': fields.many2one('ir.model.fields', 'Field', required=True),
        'relation': fields.selection([('id','ID'),('db_id','DB ID'),('search','Search')],'Field relation', help='Search use name_search to match the record'),
        'create': fields.boolean('Create entry', help="If check, if entry doesn't exist, it must be created"),
        'refkey': fields.boolean('Reference Key', help='If check, this key is equal to ID in manual import'),
    }

import_list_line()

class ir_attachment(osv.osv):
    """Inherit this class to made the CSV treatment"""
    _inherit = 'ir.attachment'

    def create(self, cr, uid, vals, context=None):
        if not context: context={}
        res = super(ir_attachment, self).create(cr, uid, vals, context)
        return res

    def write(self, cr, uid, ids, vals, context=None):
        if not context: context={}
        res = super(ir_attachment, self).write(cr, uid, ids, vals, context)
        if res:
            logger = netsvc.Logger()
            # the file are store successfully, we can 
            # for each file import, check if there insert in
            # import directory
            model_obj = self.pool.get('ir.model')
            field_obj = self.pool.get('ir.model.fields')
            import_obj = self.pool.get('document.import.list')
            line_obj = self.pool.get('document.import.list.line')
            for f in ids:
                dir_id = self.read(cr, uid, ids, ['parent_id'], context=context)[0]['parent_id'][0]

                args = [('disable','=',False), ('directory_id','=', dir_id)]
                imp_ids = import_obj.search(cr, uid, args, context=context)
                if imp_ids:
                    logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: begin import new file '.ljust(80, '*'))
                    import csv
                    import base64
                    from cStringIO import StringIO
                    imp_data = import_obj.browse(cr, uid, imp_ids[0], context=context)
                    context.update(eval(imp_data.ctx))

                    imp = model_obj.read(cr, uid, imp_data.model_id.id, context=context)
                    model = imp['model']

                    # Read all field name in the list
                    uniq_key = False
                    fld=[]
                    for l in imp_data.line_ids:
                        line = line_obj.browse(cr, uid, [l.id], context=context)[0]
                        args = {
                            'name': line.name, 
                            'field': line.field_id.name,
                            'type': line.field_id.ttype,
                            'relation': line.field_id.relation,
                            'key': line.refkey,
                            'ref': line.relation,
                        }
                        fld.append(args)
                        if line.refkey:
                            uniq_key = line.name

                    # Compose the header
                    header = []
                    if uniq_key:
                        header.append(u'id')
                    for h in fld:
                        if h['type'] not in ('many2one','one2many','many2many'):
                            header.append(h['field'])
                        else:
                            if h['ref'] in ('id', 'db_id'):
                                header.append('%s:%s' % (h['field'], h['ref']))
                            else:
                                header.append(h['field'])

                    logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: Object: %s' % imp_data.model_id.model)
                    logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: Context: %r' % context)
                    logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: Columns header: %r' % header)
                    logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: Unique key (XML id): %r' % uniq_key)

                    # Compose the line from the csv import
                    lines = []

                    val = ''
                    if 'datas' in vals:
                        val = base64.decodestring(vals['datas'])

                    fp = StringIO(val)
                    sep = chr(ord(imp_data.csv_sep[0]))
                    logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: Separator: %s ' % imp_data.csv_sep)
                    esc=None
                    if imp_data.csv_esc:
                        esc = chr(ord(imp_data.csv_esc[0]))
                        logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: Escape: %s ' % imp_data.csv_esc)

                    integ = True
                    try:
                        csvfile = csv.DictReader(fp, delimiter=sep, quotechar=esc)
                        for c in csvfile:
                            tmpline = []
                            if uniq_key:
                                tmpline.append('%s_%s' % (imp_data.model_id.model.replace('.','_') ,str(c[uniq_key])))
                            for f in fld:
                                if f['type'] in ('many2one','one2many','many2many'):
                                    if c[f['name']].find('.') > 0:
                                        tmpline.append(c[f['name']])
                                    else:
                                        tmpline.append('%s_%s' % (f['relation'].replace('.','_') ,c[f['name']]))
                                else:
                                    tmpline.append(c[f['name']])
                            logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: line: %r' % tmpline)
                            lines.append(tmpline)
                    except csv.Error, e:
                        logger.notifyChannel('import', netsvc.LOG_INFO, 'module document_csv: csv.Error: %r' % e)
                        integ = False
                    except KeyError, k:
                        logger.notifyChannel('import', netsvc.LOG_INFO, 'module document_csv: %r' % k)
                        integ = False
                    except UnicodeError:
                        logger.notifyChannel('import', netsvc.LOG_INFO, 'module document_csv: Unicode error, convert your file in UTF-8, and retry')
                        integ = False
                    except Exception, e:
                        logger.notifyChannel('import', netsvc.LOG_INFO, 'module document_csv: Error not defined ! : %r' % e)
                        integ = False
                    finally:
                        # After treatment, close th StringIO
                        fp.close()

                    if integ:
                        logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: start import')
                        # Use new cusrsor to integrate the data, because if failed the backup cannot be perform
                        cr_imp = pooler.get_db(cr.dbname).cursor()
                        try:
                            res = self.pool.get(imp_data.model_id.model).import_data(cr_imp, uid, header, lines, 'init', '', False, context=context)
                            if res[0] >= 0:
                                logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: %d line(s) imported !' % res[0])
                                cr_imp.commit()
                            else:
                                cr_imp.rollback()
                                d = ''
                                for key,val in res[1].items():
                                    d += ('\t%s: %s\n' % (str(key),str(val)))
                                error = 'Error trying to import this record:\n%s\nError Message:\n%s\n\n%s' % (d,res[2],res[3])
                                logger.notifyChannel('import', netsvc.LOG_ERROR, 'module document_csv: %r' % ustr(error))

                        except Exception, e:
                            cr_imp.rollback()
                            logger.notifyChannel('import', netsvc.LOG_ERROR, '%r' % e)
                        finally:
                            cr_imp.close()

                        logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: end import')
                    else:
                        logger.notifyChannel('import', netsvc.LOG_INFO, 'module document_csv: import canceled, correct these errors and retry')

                    try:
                        if imp_data.backup:
                            bck_file = time.strftime(imp_data.backup_filename)
                            self.write(cr, uid, ids, {'name': bck_file, 'datas_fname':bck_file, 'parent_id': imp_data.backup_dir_id.id}, context=context)
                            logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: backup file: %s ' % bck_file)
                        else:
                            self.unlink(cr, uid, ids)
                            logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: file deleted !')
                    except Exception, e:
                        logger.notifyChannel('import', netsvc.LOG_INFO, 'module document_csv: Error when backup database ! : %r' % e)

                    # Add trace on the log, when file was integrate
                    logger.notifyChannel('import', netsvc.LOG_DEBUG, 'module document_csv: end import new file '.ljust(80, '*'))
        return res

ir_attachment()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
