from cffi import FFI

ffi = FFI()

ffi.cdef("""
   typedef struct _GError GError;

    struct _GError
    {
      unsigned int domain;
      int code;
      char *message;
    };

    typedef struct _GArray GArray;

    struct _GArray {
        char *data;
        unsigned int len;
    };

    void g_type_init();
    void g_object_unref(void *pointer);
    void g_clear_error (GError **err);

    typedef struct _LibmsiDatabase LibmsiDatabase;
    typedef struct _LibmsiQuery LibmsiQuery;
    typedef struct _LibmsiRecord LibmsiRecord;
    typedef struct _LibmsiSummaryInfo LibmsiSummaryInfo;

    LibmsiDatabase * libmsi_database_new (const char *path, unsigned int flags, const char *persist, GError **error);
    LibmsiQuery * libmsi_query_new (LibmsiDatabase *database, const char *query, GError **error);
    int libmsi_query_execute (LibmsiQuery *query, LibmsiRecord *rec, GError **error);
    LibmsiRecord * libmsi_query_get_column_info (LibmsiQuery *query, int info, GError **error);
    unsigned int libmsi_record_get_field_count (const LibmsiRecord *record);
    int libmsi_record_is_null (const LibmsiRecord *record, unsigned int field);
    char * libmsi_record_get_string (const LibmsiRecord *record, unsigned int field);
    LibmsiRecord * libmsi_query_fetch (LibmsiQuery *query, GError **error);
    int libmsi_query_close (LibmsiQuery *query, GError **error);
""")

libmsi = ffi.dlopen("libmsi.so")


class MSIException(Exception):
    pass


def parse_record(record):
    if record == ffi.NULL:
        return

    record_parsed = []

    for field in range(1, libmsi.libmsi_record_get_field_count(record) + 1):
        if libmsi.libmsi_record_is_null(record, field):
            record_parsed.append(None)
        else:
            value = libmsi.libmsi_record_get_string(record, field)
            record_parsed.append(ffi.string(value))

    return record_parsed


def convert_value(v, t):
    if v is None:
        return v
    if t.lower().startswith('s') or t.lower().startswith('l'):
        return v.decode('ascii')
    if t.lower().startswith('i'):
        return int(v)
    raise MSIException('attempted to convert unhandled type!')


class MSI(object):
    __error = ffi.new("GError**")
    __database = ffi.NULL

    def __init__(self, path_to_msi, mode=1 << 0, persist=ffi.NULL):
        try:
            libmsi.g_type_init()
        except Exception:
            pass

        if persist != ffi.NULL:
            persist = ffi.new("char[]", persist)

        self.__database = libmsi.libmsi_database_new(
            ffi.new("char[]", path_to_msi.encode('utf-8')), mode, persist, self.__error)

        if self.__database == ffi.NULL or self.__error[0] != ffi.NULL:
            raise MSIException("MSI read error")

    def query(self, sql):
        error = ffi.new('GError**')
        results = []

        q = libmsi.libmsi_query_new(self.__database, ffi.new("char[]", sql.encode('utf-8')), error)

        if q == ffi.NULL or error[0] != ffi.NULL:
            raise MSIException("Query parsing error in {0}: {1}".format(sql, ffi.string(error[0].message)))

        if not libmsi.libmsi_query_execute(q, ffi.NULL, error):
            raise MSIException("Query execution error in '{0}'".format(sql))

        record_column_names = [n.decode('ascii') for n in parse_record(libmsi.libmsi_query_get_column_info(q, 0, error))]
        record_column_types = [t.decode('ascii') for t in parse_record(libmsi.libmsi_query_get_column_info(q, 1, error))]
        type_map = dict(zip(record_column_names, record_column_types))

        while True:
            record = libmsi.libmsi_query_fetch(q, error)

            if record == ffi.NULL or error[0] != ffi.NULL:
                break

            record_dict = {}
            for k, v in zip(record_column_names, parse_record(record)):
                record_dict[k] = convert_value(v, type_map[k])
            results.append(record_dict)

            libmsi.g_object_unref(record)

        if error != ffi.NULL:
            libmsi.g_clear_error(self.__error)

        if q != ffi.NULL:
            libmsi.libmsi_query_close(q, ffi.NULL)

        return results

    def __del__(self):
        if self.__database != ffi.NULL:
            libmsi.g_object_unref(self.__database)

        if self.__error != ffi.NULL:
            libmsi.g_clear_error(self.__error)
