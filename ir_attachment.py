# -*- coding: utf-8 -*-
##############################################################################
#
#    document_csv module for OpenERP, Import structure in CSV
#    Copyright (C) 2011 SYLEAM (<http://www.syleam.fr/>)
#              Christophe CHAUVET <christophe.chauvet@syleam.fr>
#    Copyright (C) 2011 Camptocamp (http://www.camptocamp.com)
#              Guewen Baconnier
#
#    This file is a part of document_csv
#
#    document_csv is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    document_csv is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from osv import osv
from tools import ustr
from tools import config

import re
import time
import base64
import csv
import pooler
import logging


try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO



class ir_attachment(osv.osv):
    """Inherit this class to made the CSV treatment"""
    _inherit = 'ir.attachment'

    _logger = logging.getLogger('document_csv')

    def import_csv(self, cr, uid, format_id, content, email_to, context):
        self._logger.info('Start new CSV import')

        # launch process as multithread
        self._logger.info('Launch import as thread')
        self.on_execute(cr, uid, cr.dbname, format_id, StringIO(base64.decodestring(content)), email_to, context)

        return True

    def on_execute(self, cr, uid, dbname, format_id, cfp, email_to, context=None):
        if context is None:
            context = {}

        cr = pooler.get_db(dbname).cursor()
        res = False

        # the file are store successfully, we can
        # for each file import, check if there insert in
        # import directory
        model_obj = self.pool.get('ir.model')
        field_obj = self.pool.get('ir.model.fields')
        import_obj = self.pool.get('document.import.list')
        line_obj = self.pool.get('document.import.list.line')

        self._logger.info('module document_csv: begin import new file '.ljust(80, '*'))
        imp_data = import_obj.browse(cr, uid, format_id, context=context)
        context.update(eval(imp_data.ctx))

        logfp = StringIO()

        def log_compose(message):
            logfp.write(time.strftime('[%Y-%m-%d %H:%M:%S] '))
            logfp.write(message.encode('utf-8') + '\n')
            return message

        # Read all field name in the list
        uniq_key = []
        rel_uniq_key = {}
        fld = []
        for l in imp_data.line_ids:
            args = {
                'name': l.name,
                'field': l.field_id.name,
                'rel_field': l.field_relation_id.name,
                'type': l.field_id.ttype,
                'relation': l.field_id.relation,
                'key': l.refkey,
                'ref': l.relation,
            }
            fld.append(args)
            if l.refkey and l.field_id.ttype not in ('many2one', 'one2many', 'many2many'):
                uniq_key.append(l.name)
            elif l.refkey and l.field_id.ttype in ('many2one', 'one2many', 'many2many'):
                if not rel_uniq_key.get(l.field_id.name):
                    rel_uniq_key[l.field_id.name] = []
                rel_uniq_key[l.field_id.name].append(l.name)

        # If "key field" is filled, replace the uniq_key list
        if imp_data.key_field_name:
            uniq_key = [imp_data.key_field_name]

        # Compose the header
        header = []
        rej_header = []
        if uniq_key:
            header.append(u'id')
        if rel_uniq_key:
            for x in rel_uniq_key:
                header.append('%s/id' % x)

        for h in fld:
            rej_header.append(h['name'])
            if h['type'] not in ('many2one', 'one2many', 'many2many'):
                header.append(h['field'])
            else:
                if h['rel_field']:
                    header.append('%s/%s' % (h['field'], h['rel_field']))
                elif h['ref'] == 'db_id':
                    header.append('%s/.id' % (h['field'],))
                elif h['ref'] == 'id':
                    header.append('%s/id' % (h['field'],))
                else:
                    header.append(h['field'].encode('utf-8'))

        self._logger.debug('module document_csv: ' + log_compose('%s: %s' % ('Object', imp_data.model_id.model)))
        self._logger.debug('module document_csv: ' + log_compose('%s: %r' % ('Context', context)))
        self._logger.debug('module document_csv: ' + log_compose('Columns header original : %s' % ', '.join(rej_header)))
        self._logger.debug('module document_csv: ' + log_compose('Columns header translate: %s' % ', '.join(header)))
        self._logger.debug('module document_csv: ' + log_compose('%s: %r' % ('Unique key (XML id)', uniq_key)))
        self._logger.debug('module document_csv: ' + log_compose('%s: %s' % ('Send report to', email_to)))

        # Compose the line from the csv import
        lines = []
        rej_lines = []

        sep = chr(ord(imp_data.csv_sep[0]))
        self._logger.debug('module document_csv: ' + log_compose('Separator: %s ' % imp_data.csv_sep))

        esc = None
        if imp_data.csv_esc:
            esc = chr(ord(imp_data.csv_esc[0]))
            self._logger.debug('module document_csv: ' + log_compose('Escape: %s ' % imp_data.csv_esc))

        def real_id(value, model):
            """
            Find if we have a prefix
            """
            if value.startswith('.'):  # Don't protect id
                return value
            if value.find(model.replace('.', '_')) >= 0:  # We have prefix, return the original string
                if value.find('.') >= 0:
                    return value
                else:
                    return '.' + value
            return '.%s_%s' % (model.replace('.', '_'), value)

        error = False
        integ = True
        try:
            self._logger.debug('module document_csv: ' + log_compose('Read the CSV file'))
            self._logger.debug('module document_csv: header: %r ***(%d)***' % (header, len(header)))
            csvfile = csv.DictReader(cfp, delimiter=sep, quotechar=esc)
            for c in csvfile:
                tmpline = []
                rejline = []
                if uniq_key:
                    res_tmp = ''
                    for x in uniq_key:
                        res_tmp += str(re.sub('\W', '_', c[x]))
                    tmpline.append(str(real_id(res_tmp, imp_data.model_id.model)))

                if rel_uniq_key:
                    for x in rel_uniq_key:
                        res_tmp = ''
                        for z in rel_uniq_key[x]:
                            res_tmp += str(c[z])
                        tmpline.append(res_tmp)

                for f in fld:
                    fld_name = c[f['name'].encode('utf-8')]
                    if f['type'] in ('many2one', 'one2many', 'many2many'):
                        if not c[f['name'].encode('utf-8')].find('.') > 0:
                            if f['ref'] == 'id':
                                # If object name is available as prefix don't add it
                                fld_name = str(real_id(c[f['name']].encode('utf-8'), f['relation']))
                                #fld_name = '%s_%s' % (f['relation'].replace('.', '_'), c[f['name'].encode('utf-8')])
                    tmpline.append(fld_name)
                    rejline.append(c[f['name'].encode('utf-8')])

                self._logger.debug('module document_csv: line: %r ***(%d)***' % (tmpline, len(tmpline)))
                for i in range(len(tmpline)):
                    if i == 0:
                        tmpline[i] = tmpline[i]
                    else:
                        tmpline[i] = ustr(tmpline[i])
                lines.append(tmpline)
                rej_lines.append(rejline)
        except csv.Error, e:
            self._logger.info('module document_csv: ' + log_compose('csv.Error: %r' % e))
            error = 'csv Error, %s' % str(e)
            integ = False
        except KeyError, k:
            self._logger.info('module document_csv: ' + log_compose('ERROR: The columns "%s" cannot be found, check if no extra space around the column title' % k.args[0]))
            error = 'KeyError, %s' % str(k)
            integ = False
        except UnicodeError:
            self._logger.info('module document_csv: ' + log_compose('Unicode error, convert your file in UTF-8, and retry'))
            error = 'Unicode error, convert your file in UTF-8, and retry'
            integ = False
        except Exception, e:
            self._logger.info('module document_csv: ' + log_compose('Error not defined ! : %r' % e))
            error = 'Error not defined'
            integ = False
        finally:
            # After treatment, close th StringIO
            cfp.close()

        if integ:
            self._logger.debug('module document_csv: ' + log_compose('start import'))
            # Use new cusrsor to integrate the data, because if failed the backup cannot be perform
            cr_imp = pooler.get_db(cr.dbname).cursor()
            current_model = self.pool.get(imp_data.model_id.model)
            try:
                if imp_data.err_reject:
                    self._logger.debug('module document_csv: ' + log_compose('Global mode'))
                    res = current_model.import_data(cr_imp, uid, header, lines, 'init', '', False, context=context)
                    if res[0] >= 0:
                        self._logger.debug('module document_csv: ' + log_compose('%d line(s) imported !' % res[0]))
                        cr_imp.commit()
                    else:
                        cr_imp.rollback()
                        d = ''
                        for key, val in res[1].items():
                            d += ('\t%s: %s\n' % (str(key), str(val)))
                        error = 'Error trying to import this record:\n%s\nError Message:\n%s\n\n%s' % (d, res[2], res[3])
                        self._logger.error('module document_csv: ' + log_compose('%r' % ustr(error)))

                    if current_model._parent_store:
                        self._logger.debug('module document_csv: ' + log_compose('Compute the parent_store'))
                        current_model._parent_store_compute(cr)
                else:
                    rejfp = StringIO()
                    count_success = 0
                    count_errors = 0
                    self._logger.debug('module document_csv: ' + log_compose('Unit mode'))
                    rej_file = csv.writer(rejfp, delimiter=sep, quotechar=esc, quoting=csv.QUOTE_NONNUMERIC)
                    rej_file.writerow([x.encode('utf-8') for x in rej_header])

                    cpt_lines = 0
                    for li in lines:
                        self._logger.debug('module document_csv: Import line %d' % (cpt_lines + 1))
                        try:
                            res = current_model.import_data(cr_imp, uid, header, [li], 'init', '', False, context=context)
                        except Exception, e:
                            res = [-1, {}, e.args[0], '']

                        if res[0] >= 0:
                            count_success += 1
                            cr_imp.commit()
                        else:
                            count_errors += 1
                            cr_imp.rollback()
                            log_compose(4 * '*')
                            log_compose('Error line %d: %s' % (cpt_lines + 2, ', '.join([x.decode('utf-8') for x in rej_lines[cpt_lines]])))
                            log_compose('Error message: %s' % res[2].encode('utf-8'))
                            rej_file.writerow(rej_lines[cpt_lines])
                        cpt_lines += 1

                    log_compose(4 * '*')
                    self._logger.debug('module document_csv: ' + log_compose('%d line(s) imported !' % count_success))
                    self._logger.debug('module document_csv: ' + log_compose('%d line(s) rejected !' % count_errors))
                    #if current_model._parent_store:
                    #    self._logger.debug('module document_csv: ' + log_compose('Compute the parent_store'))
                    #    current_model._parent_store_compute(cr)

                    if count_errors:
                        rej_name = time.strftime(imp_data.reject_filename)
                        rej_enc = base64.encodestring(rejfp.getvalue())
                        rejfp.close()
                        rej_args = {
                            'name': rej_name,
                            'datas_fname': rej_name,
                            'parent_id': imp_data.reject_dir_id.id,
                            'datas': rej_enc,
                        }
                        if not self.create(cr, uid, rej_args):
                            self._logger.error('module document_csv: impossible to create the reject file!')

            except Exception, e:
                cr_imp.rollback()
                error = e.message
                self._logger.error(log_compose(e.message))
            finally:
                cr_imp.close()

            self._logger.debug('module document_csv: ' + log_compose('end import'))
        else:
            self._logger.info('module document_csv: ' + log_compose('import canceled, correct these errors and retry'))

        try:
            if imp_data.backup:
                # TODO backup this file, only in memory for now
                bck_file = time.strftime(imp_data.backup_filename)
                #self.write(cr, uid, ids, {'name': bck_file, 'datas_fname':bck_file, 'parent_id': imp_data.backup_dir_id.id}, context=context)
                self._logger.debug('module document_csv: ' + log_compose('backup file: %s ' % bck_file))
            else:
                self._logger.debug('module document_csv: ' + log_compose('file deleted !'))
        except Exception, e:
            self._logger.info('module document_csv: ' + log_compose('Error when backup database ! : %r' % e))

        ## save the log file
        log_name = time.strftime(imp_data.log_filename)
        log_content = logfp.getvalue()
        log_enc = base64.encodestring(log_content)
        logfp.close()
        log_args = {
            'name': log_name,
            'datas_fname': log_name,
            'parent_id': imp_data.log_dir_id.id,
            'datas': log_enc,
        }
        if not self.create(cr, uid, log_args):
            self._logger.error('module document_csv: impossible to create the log file!')

        ir_mail_server = self.pool.get('ir.mail_server')

        if email_to or imp_data.err_mail:
            res_email_to = email_to and [email_to] or False

            email_from = imp_data.mail_from
            if not email_from:
                email_from = config.get('email_from')

            log_attachment = [(log_name, log_content)]
            legend = {}
            if (not isinstance(res, bool) and res[0] >= 0) and integ:
                legend['count'] = res[0]
                subject = imp_data.mail_subject and (imp_data.mail_subject % legend) or 'No subject'
                body = imp_data.mail_body and (imp_data.mail_body % legend) or 'No body'
                mail_cc = [imp_data.mail_cc]
            else:
                subject = imp_data.mail_subject_err and (imp_data.mail_subject_err % legend) or 'No subject'
                body = imp_data.mail_body_err and (imp_data.mail_body_err % {'error': error}) or 'No body'
                mail_cc = [imp_data.mail_cc_err]

            if mail_cc and not res_email_to:
                res_email_to = mail_cc
                mail_cc = False

            if email_from and res_email_to:
                msg = ir_mail_server.build_email(email_from=email_from,
                                                 email_to=res_email_to,
                                                 email_cc=mail_cc,
                                                 subject=subject,
                                                 body=body,
                                                 attachments=log_attachment)
                ir_mail_server.send_email(cr, uid, msg, context=context)
                self._logger.debug('module document_csv: Sending mail [OK]')
            else:
                self._logger.warning('module document_csv: Sending mail [FAIL], missing email "from" or "to"')

        # Add trace on the log, when file was integrate
        self._logger.debug('module document_csv: end import new file '.ljust(80, '*'))
        self._logger.info('Finish import as thread')

        cr.commit()
        cr.close()
        return True

ir_attachment()


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
