#!/usr/bin/python2.7
# -*- encoding: UTF8 -*-

"""
Copyright: Eesti Vabariigi Valimiskomisjon
(Estonian National Electoral Committee), www.vvk.ee
Written in 2004-2014 by Cybernetica AS, www.cyber.ee

This work is licensed under the Creative Commons
Attribution-NonCommercial-NoDerivs 3.0 Unported License.
To view a copy of this license, visit
http://creativecommons.org/licenses/by-nc-nd/3.0/.
"""

import os
import sys
import subprocess
import base64
import time

from election import Election
import evlog
import evreg
import ksum
import evcommon

import inputlists
import formatutil

VOTING_ID_LENGTH = 28
DECRYPT_PROGRAM = "threaded_decrypt"
SIGN_PROGRAM = "sign_data"
CORRUPTED_VOTE = "xxx"

CERT_PATH = "/usr/lunasa/cert/vvk.der"
CERT = "vvk.der"

README_PATH = "/usr/share/doc/evote-hlr/README"
README = "README"


ENV_EVOTE_TMPDIR = "EVOTE_TMPDIR"

G_DECRYPT_ERRORS = {
    1: 'Dekrüpteerija sai vale arvu argumente',
    2: 'Häälte faili ei önnestunud lugemiseks avada',
    3: 'Dekrüptitud häälte faili ei õnnestunud kirjutamiseks avada',
    4: 'Häälte failis puudus versiooni number',
    5: 'Häälte failis puudus valimiste identifikaator',
    6: 'Viga sisendi lugemisel',
    7: 'Viga väljundi kirjutamisel',
    8: 'Häälte faili rida ei vastanud formaadile',
    9: 'Dekrüpteerija ebaõnnestus'}


G_SIGN_ERRORS = {
    1: 'Allkirjastaja sai vale arvu argumente',
    2: 'Tulemusfaili ei önnestunud lugemiseks avada',
    3: 'Allkirjafaili ei õnnestunud kirjutamiseks avada',
    4: 'Viga sisendi lugemisel',
    5: 'Viga väljundi kirjutamisel',
    6: 'Allkirjastaja ebaõnnestus'}


class DecodedVoteList(inputlists.InputList):

    def __init__(self, vote_handler, jsk=None):
        inputlists.InputList.__init__(self)
        self.name = 'Dekrüpteeritud häälte nimekiri'
        self.jsk = jsk
        self._vote_handler = vote_handler

    def checkuniq(self, line):
        return True

    def dataline(self, line):
        lst = line.split('\t')
        if not len(lst) == 6:
            self.errform('Kirjete arv real')
            return False
        if not formatutil.is_jaoskonna_number_kov_koodiga(lst[0], lst[1]):
            self.errform('Valimisjaoskonna number KOV koodiga')
            return False
        if not formatutil.is_ringkonna_number_kov_koodiga(lst[2], lst[3]):
            self.errform('Ringkonna number KOV koodiga')
            return False
        if not formatutil.is_base64(lst[4]):
            self.errform('Algne hääl')
            return False
        if not formatutil.is_base64(lst[5]):
            self.errform('Dekrüpteeritud hääl')
            return False
        if self.jsk:
            if not self.jsk.has_ring((lst[2], lst[3])):
                self.errcons('Olematu ringkond')
                return False
            if not self.jsk.has_stat((lst[2], lst[3]), (lst[0], lst[1])):
                self.errcons('Olematu jaoskond')
                return False

        if not self._vote_handler.handle_vote(lst, self.processed()):
            self.errcons('Viga hääle käitlemisel')
            return False

        return True


def ringkonnad_cmp(dist1, dist2):
    i1 = int(dist1[0])
    i2 = int(dist2[0])
    if (i1 != i2):
        return i1 - i2
    else:
        j1 = int(dist1[1])
        j2 = int(dist2[1])
        return j1 - j2
    return 0


def valikud_cmp(choi1, choi2):
    code1 = choi1.split('.')[1]
    code2 = choi2.split('.')[1]
    if (code1 == 'kehtetu') or (code2 == 'kehtetu'):
        if code1 == code2:
            return 0
        if code1 == 'kehtetu':
            return 1
        return -1
    return int(code1) - int(code2)


class ChoicesCounter:

    def __init__(self):
        self.__cdata = {}
        self.__ddata = {}
        self.__count = 0

    def add_vote(self, ring, stat, choice):
        self.__cdata[ring][stat][choice] += 1
        self.__ddata[ring][choice] += 1

    def _to_key(self, reg_key):
        lst = reg_key.split('_')
        return (lst[0], lst[1])

    def load(self, reg):
        for rk in reg.list_keys(['hlr', 'choices']):
            r_key = self._to_key(rk)
            self.__cdata[r_key] = {}
            if r_key not in self.__ddata:
                self.__ddata[r_key] = {}
            for stat in reg.list_keys(['hlr', 'choices', rk]):
                d_key = self._to_key(stat)
                self.__cdata[r_key][d_key] = {}
                for choi in reg.list_keys(['hlr', 'choices', rk, stat]):
                    self.__cdata[r_key][d_key][choi] = 0
                    if choi not in self.__ddata[r_key]:
                        self.__ddata[r_key][choi] = 0

    def has_ring(self, ring):
        return (ring in self.__cdata)

    def has_stat(self, ring, stat):
        return (stat in self.__cdata[ring])

    def has_choice(self, ring, stat, choice):
        return (choice in self.__cdata[ring][stat])

    def count(self):
        return self.__count

    def _sort(self, lst, cmp_method):
        keys = lst.keys()
        keys.sort(cmp_method)
        return keys

    def outputstat(self, out_f):
        self.__count = 0

        for rk in self._sort(self.__cdata, ringkonnad_cmp):
            for stat in self._sort(self.__cdata[rk], ringkonnad_cmp):
                for choice in self._sort(self.__cdata[rk][stat], valikud_cmp):
                    self.__count += self.__cdata[rk][stat][choice]
                    count_line =\
                        [stat[0], stat[1], rk[0], rk[1],
                         str(self.__cdata[rk][stat][choice]),
                         choice.split('.')[1]]
                    out_f.write("\t".join(count_line) + "\n")

    def outputdist(self, out_f):
        for rk in self._sort(self.__ddata, ringkonnad_cmp):
            for choice in self._sort(self.__ddata[rk], valikud_cmp):
                count_line = [rk[0], rk[1],
                              str(self.__ddata[rk][choice]),
                              choice.split('.')[1]]
                out_f.write("\t".join(count_line) + "\n")


def _sig(inf):
    return "%s.sig" % inf


class HLR:

    """
    Häältelugemisrakendus
    """

    def __init__(self, elid, tmpdir):

        self._elid = elid
        evlog.AppLog().set_app('HLR', self._elid)
        self._reg = Election().get_sub_reg(self._elid)
        self._log4 = evlog.Logger('log4')
        self._log5 = evlog.Logger('log5')
        self._log4.set_format(evlog.EvLogFormat())
        self._log5.set_format(evlog.EvLogFormat())
        self._log4.set_logs(self._reg.path(['common', 'log4']))
        self._log5.set_logs(self._reg.path(['common', 'log5']))

        tmpreg = evreg.Registry(root=tmpdir)
        tmpreg.ensure_key([])
        tmpreg.delete_sub_keys([])
        self.output_file = tmpreg.path(['decrypted_votes'])
        self.decrypt_prog = DECRYPT_PROGRAM
        self.sign_prog = SIGN_PROGRAM
        self.__cnt = ChoicesCounter()

    def __del__(self):
        try:
            os.remove(self.output_file)
        except:
            pass

    def _decrypt_votes(self, pin):

        input_file = self._reg.path(['hlr', 'input', 'votes'])
        token_name = Election().get_hsm_token_name()
        priv_key_label = Election().get_hsm_priv_key()
        pkcs11lib = Election().get_pkcs11_path()
        args = [input_file,
                self.output_file,
                token_name,
                priv_key_label,
                pin,
                pkcs11lib]

        exit_code = 0

        try:
            exit_code = subprocess.call([self.decrypt_prog] + args)
        except OSError as oserr:
            errstr = "Häälte faili '%s' dekrüpteerimine nurjus: %s" % \
                (input_file, oserr)
            evlog.log_error(errstr)
            return False

        if exit_code == 0:
            return True

        if exit_code > 0:
            errstr2 = "Tundmatu viga"
            if exit_code in G_DECRYPT_ERRORS:
                errstr2 = G_DECRYPT_ERRORS[exit_code]

            errstr = \
                "Häälte faili '%s' dekrüpteerimine nurjus: %s (kood %d)" % \
                (input_file, errstr2, exit_code)
            evlog.log_error(errstr)
            return False

        errstr = "Häälte faili '%s' dekrüpteerimine nurjus (signaal %d)" % \
            (input_file, exit_code)
        evlog.log_error(errstr)
        return False

    def _sign_result(self, pin, input_file):

        token_name = Election().get_hsm_token_name()
        priv_key_label = Election().get_hsm_priv_key()
        pkcs11lib = Election().get_pkcs11_path()
        args = [input_file,
                _sig(input_file),
                token_name,
                priv_key_label,
                pin,
                pkcs11lib]

        exit_code = 0

        try:
            exit_code = subprocess.call([self.sign_prog] + args)
        except OSError as oserr:
            errstr = "Tulemuste faili '%s' allkirjastamine nurjus: %s" % \
                (input_file, oserr)
            evlog.log_error(errstr)
            return False

        if exit_code == 0:
            return True

        if exit_code > 0:
            errstr2 = "Tundmatu viga"
            if exit_code in G_SIGN_ERRORS:
                errstr2 = G_SIGN_ERRORS[exit_code]

            errstr = \
                "Tulemuste faili '%s' allkirjastamine nurjus: %s (kood %d)" % \
                (input_file, errstr2, exit_code)
            evlog.log_error(errstr)
            return False

        errstr = "Tulemuste faili '%s' allkirjastamine nurjus (signaal %d)" % \
            (input_file, exit_code)
        evlog.log_error(errstr)
        return False

    def _sign_result_files(self, pin):
        f1 = self._reg.path(
            ['hlr', 'output', evcommon.ELECTIONRESULT_FILE])
        f2 = self._reg.path(
            ['hlr', 'output', evcommon.ELECTIONRESULT_STAT_FILE])

        ret1 = self._sign_result(pin, f1)
        ret2 = self._sign_result(pin, f2)

        if (ret1 and ret2):
            import zipfile
            zippath = self._reg.path(
                ['hlr', 'output', evcommon.ELECTIONRESULT_ZIP_FILE])
            rzip = zipfile.ZipFile(zippath, "w")
            rzip.write(f1, evcommon.ELECTIONRESULT_FILE)
            rzip.write(_sig(f1), _sig(evcommon.ELECTIONRESULT_FILE))
            rzip.write(f2, evcommon.ELECTIONRESULT_STAT_FILE)
            rzip.write(_sig(f2), _sig(evcommon.ELECTIONRESULT_STAT_FILE))

            if os.path.isfile(CERT_PATH) and os.access(CERT_PATH, os.R_OK):
                rzip.write(CERT_PATH, CERT)

            if os.path.isfile(README_PATH) and os.access(README_PATH, os.R_OK):
                rzip.write(README_PATH, README)

            rzip.close()
            return True
        else:
            return False

    def _add_kehtetu(self, ringkond, district):
        self.__cnt.add_vote(ringkond, district, ringkond[0] + ".kehtetu")

    def _check_vote(self, ringkond, district, haal, line_nr):

        ret = True
        if haal == CORRUPTED_VOTE:
            errstr = "Häält (rida=%d) ei õnnestunud dekrüptida" % line_nr
            evlog.log_error(errstr)
            ret = False
        else:
            lst = haal.split('\n')
            if ((len(lst) != 4) or
                    (lst[0] != evcommon.VERSION) or
                    (lst[1] != self._elid) or
                    (lst[3] != "")):
                ret = False
            else:
                if not formatutil.is_valiku_kood(lst[2]):
                    ret = False
                elif lst[2].split(".")[0] != ringkond[0]:
                    ret = False

        if ret and self.__cnt.has_choice(ringkond, district, lst[2]):
            self.__cnt.add_vote(ringkond, district, lst[2])
        else:
            ret = False
            self._add_kehtetu(ringkond, district)

        return ret

    def handle_vote(self, votelst, line_nr):
        try:
            dist = (votelst[0], votelst[1])
            ring = (votelst[2], votelst[3])
            vote = base64.decodestring(votelst[5])
            if not self._check_vote(ring, dist, vote, line_nr):
                self._log4.log_info(
                    tyyp=4,
                    haal=base64.decodestring(votelst[4]),
                    ringkond_omavalitsus=votelst[2],
                    ringkond=votelst[3])
            else:
                self._log5.log_info(
                    tyyp=5,
                    haal=base64.decodestring(votelst[4]),
                    ringkond_omavalitsus=votelst[2],
                    ringkond=votelst[3])
            return True
        except:
            evlog.log_exception()
            return False

    def _count_votes(self):
        dvl = DecodedVoteList(self, self.__cnt)
        dvl.attach_logger(evlog.AppLog())
        dvl.attach_elid(self._elid)
        if not dvl.check_format(self.output_file, 'Loen hääli: '):
            evlog.log_error('Häälte lugemine ebaõnnestus')
            return False
        return True

    def _write_result(self):
        result_dist_fn = self._reg.path(
            ['hlr', 'output', evcommon.ELECTIONRESULT_FILE])
        out_f = file(result_dist_fn, 'w')
        out_f.write(evcommon.VERSION + '\n' + self._elid + '\n')
        self.__cnt.outputdist(out_f)
        out_f.close()
        ksum.store(result_dist_fn)

        result_stat_fn = self._reg.path(
            ['hlr', 'output', evcommon.ELECTIONRESULT_STAT_FILE])
        out_f = file(result_stat_fn, 'w')
        out_f.write(evcommon.VERSION + '\n' + self._elid + '\n')
        self.__cnt.outputstat(out_f)
        out_f.close()
        ksum.store(result_stat_fn)

        print "Hääled (%d) on loetud." % self.__cnt.count()

    def _check_logs(self):
        log_lines = 0
        log_lines = log_lines + self._log4.lines_in_file()
        log_lines = log_lines + self._log5.lines_in_file()
        # remove header
        log_lines = log_lines - 6
        if log_lines != self.__cnt.count():
            errstr = "Log4 ja Log5 ridade arv (%d) "\
                "ei klapi häälte arvuga (%d)" % \
                (log_lines, self.__cnt.count())
            evlog.log_error(errstr)
            return False
        return True

    def _create_logs(self):

        with open(self._reg.path(['common', 'log4']), 'w') as log4_f:
            log4_f.write(evcommon.VERSION + "\n")
            log4_f.write(self._elid + "\n")
            log4_f.write("4\n")

        with open(self._reg.path(['common', 'log5']), 'w') as log5_f:
            log5_f.write(evcommon.VERSION + "\n")
            log5_f.write(self._elid + "\n")
            log5_f.write("5\n")
        return True

    def run(self, pin):
        try:
            self.__cnt.load(self._reg)
            if not self._decrypt_votes(pin):
                return False
            if not self._create_logs():
                return False
            if not self._count_votes():
                return False
            self._write_result()
            if not self._check_logs():
                return False
            if not self._sign_result_files(pin):
                return False
            return True
        except:
            evlog.log_exception()
            return False


def usage():
    print "Kasutamine:"
    print "    %s <valimiste-id> <PIN>" % sys.argv[0]
    sys.exit(1)


def main_function():
    if len(sys.argv) != 3:
        usage()

    start_time = time.time()

    # See on kataloom (mälufailisüsteem) kus vahetulemusi hoiame.
    if ENV_EVOTE_TMPDIR not in os.environ:
        print 'Keskkonnamuutuja %s seadmata\n' % (ENV_EVOTE_TMPDIR)
        sys.exit(1)

    _hlr = HLR(sys.argv[1], os.environ[ENV_EVOTE_TMPDIR])
    retval = _hlr.run(sys.argv[2])

    print time.strftime("\nAega kulus %H:%M:%S",
                        time.gmtime(long(time.time() - start_time)))

    if retval:
        print 'Häälte lugemine õnnestus'
        sys.exit(0)

    print 'Häälte lugemine ebaõnnestus'
    print 'Viimane viga: %s' % evlog.AppLog().last_message()
    sys.exit(1)


if __name__ == '__main__':
    main_function()

# vim:set ts=4 sw=4 et fileencoding=utf8:
