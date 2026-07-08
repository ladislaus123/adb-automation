import copy

import mysql.connector


class FakeMariaDBConnection:
    def __init__(self):
        self.devices = []
        self.send_jobs = []
        self.next_id = 1
        self.next_job_id = 1
        self.closed = False
        self.transactions_started = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, dictionary=False):
        return FakeCursor(self, dictionary=dictionary)

    def start_transaction(self):
        self.transactions_started += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, conn, dictionary=False):
        self.conn = conn
        self.dictionary = dictionary
        self.lastrowid = None
        self.result = None
        self.closed = False

    def execute(self, query, params=None):
        params = params or ()
        normalized = " ".join(query.lower().split())

        if normalized.startswith("insert into devices"):
            self._insert_device(params)
            return

        if normalized.startswith("insert into send_jobs"):
            self._insert_send_job(params)
            return

        if normalized.startswith("select * from devices where id"):
            self.result = self._find_by_id(params[0])
            return

        if normalized.startswith("select * from send_jobs where id"):
            self.result = self._find_job_by_id(params[0])
            return

        if normalized.startswith("select count(*) as job_count from send_jobs"):
            self.result = self._count_normal_jobs_by_device(params[0], params[1])
            return

        if normalized.startswith("select distinct phone from send_jobs"):
            self.result = self._list_succeeded_phones_by_device(
                params[0], params[1], params[2]
            )
            return

        if (
            normalized.startswith("select * from send_jobs where status = %s")
            and "order by id asc" in normalized
        ):
            self.result = self._list_jobs_by_status(params[0], ascending=True)
            return

        if (
            normalized.startswith("select * from send_jobs where status = %s")
            and "order by id desc" in normalized
        ):
            self.result = self._list_jobs_by_status(params[0], limit=params[1])
            return

        if normalized.startswith("select * from send_jobs order by id desc"):
            self.result = self._list_jobs(limit=params[0])
            return

        if normalized.startswith("select * from devices where name"):
            self.result = self._find_by_name(params[0])
            return

        if normalized.startswith("select * from devices where ip"):
            self.result = self._find_by_endpoint(params[0], params[1])
            return

        if normalized.startswith("select * from devices order by id asc"):
            self.result = [copy.deepcopy(device) for device in self.conn.devices]
            return

        if normalized.startswith("update devices set worker_id = %s"):
            self._lease_device(params)
            return

        if (
            normalized.startswith("update devices set worker_id = null")
            and "and worker_id = %s and locked_until = %s" in normalized
        ):
            self._release_device(params)
            return

        if normalized.startswith("update devices set worker_id = null"):
            self._unlock_device(params)
            return

        if normalized.startswith("update devices set last_seen_at"):
            self._mark_seen(params)
            return

        if normalized.startswith("update send_jobs set status = %s, queue_worker_id"):
            self._claim_job(params)
            return

        if normalized.startswith("update send_jobs set status = %s, error"):
            self._fail_job(params)
            return

        if normalized.startswith("update send_jobs set status = %s, finished_at"):
            self._complete_job(params)
            return

        if normalized.startswith("create table"):
            return

        raise AssertionError(f"unexpected query: {query}")

    def fetchone(self):
        if self.result is None:
            return None
        if isinstance(self.result, list):
            return copy.deepcopy(self.result[0]) if self.result else None
        return copy.deepcopy(self.result)

    def fetchall(self):
        if self.result is None:
            return []
        if isinstance(self.result, list):
            return copy.deepcopy(self.result)
        return [copy.deepcopy(self.result)]

    def close(self):
        self.closed = True

    def _insert_device(self, params):
        name, ip, port, created_at, updated_at = params
        for device in self.conn.devices:
            if device["name"] == name or (
                device["ip"] == ip and device["port"] == port
            ):
                raise mysql.connector.IntegrityError("duplicate device")

        device = {
            "id": self.conn.next_id,
            "name": name,
            "ip": ip,
            "port": port,
            "worker_id": None,
            "locked_until": None,
            "last_seen_at": None,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        self.conn.devices.append(device)
        self.lastrowid = device["id"]
        self.conn.next_id += 1

    def _insert_send_job(self, params):
        (
            status,
            endpoint,
            device_id,
            device_selector,
            phone,
            text,
            file_path,
            business,
            worker_id,
            lease_seconds,
            created_at,
            updated_at,
        ) = params
        job = {
            "id": self.conn.next_job_id,
            "status": status,
            "endpoint": endpoint,
            "device_id": device_id,
            "device_selector": device_selector,
            "phone": phone,
            "text": text,
            "file_path": file_path,
            "business": business,
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
            "queue_worker_id": None,
            "device_locked_until": None,
            "error": None,
            "created_at": created_at,
            "updated_at": updated_at,
            "started_at": None,
            "finished_at": None,
        }
        self.conn.send_jobs.append(job)
        self.lastrowid = job["id"]
        self.conn.next_job_id += 1

    def _find_by_id(self, device_id):
        for device in self.conn.devices:
            if device["id"] == device_id:
                return copy.deepcopy(device)
        return None

    def _find_job_by_id(self, job_id):
        for job in self.conn.send_jobs:
            if job["id"] == job_id:
                return copy.deepcopy(job)
        return None

    def _list_jobs_by_status(self, status, limit=None, ascending=False):
        jobs = [job for job in self.conn.send_jobs if job["status"] == status]
        jobs.sort(key=lambda job: job["id"], reverse=not ascending)
        if limit is not None:
            jobs = jobs[:limit]
        return [copy.deepcopy(job) for job in jobs]

    def _list_jobs(self, limit=None):
        jobs = sorted(self.conn.send_jobs, key=lambda job: job["id"], reverse=True)
        if limit is not None:
            jobs = jobs[:limit]
        return [copy.deepcopy(job) for job in jobs]

    def _count_normal_jobs_by_device(self, device_id, stochastic_endpoint):
        count = sum(
            1
            for job in self.conn.send_jobs
            if job["device_id"] == device_id and job["endpoint"] != stochastic_endpoint
        )
        return {"job_count": count}

    def _list_succeeded_phones_by_device(self, device_id, status, stochastic_endpoint):
        phones = []
        for job in self.conn.send_jobs:
            if (
                job["device_id"] == device_id
                and job["status"] == status
                and job["endpoint"] != stochastic_endpoint
                and job["phone"] not in phones
            ):
                phones.append(job["phone"])
        return [{"phone": phone} for phone in phones]

    def _find_by_name(self, name):
        for device in self.conn.devices:
            if device["name"] == name:
                return copy.deepcopy(device)
        return None

    def _find_by_endpoint(self, ip, port):
        for device in self.conn.devices:
            if device["ip"] == ip and device["port"] == port:
                return copy.deepcopy(device)
        return None

    def _lease_device(self, params):
        worker_id, locked_until, updated_at, device_id = params
        device = self._device_ref(device_id)
        device["worker_id"] = worker_id
        device["locked_until"] = locked_until
        device["updated_at"] = updated_at

    def _release_device(self, params):
        updated_at, device_id, worker_id, locked_until = params
        device = self._device_ref(device_id)
        if device["worker_id"] == worker_id and device["locked_until"] == locked_until:
            device["worker_id"] = None
            device["locked_until"] = None
            device["updated_at"] = updated_at

    def _unlock_device(self, params):
        updated_at, device_id = params
        device = self._device_ref(device_id)
        device["worker_id"] = None
        device["locked_until"] = None
        device["updated_at"] = updated_at

    def _mark_seen(self, params):
        last_seen_at, updated_at, device_id = params
        device = self._device_ref(device_id)
        device["last_seen_at"] = last_seen_at
        device["updated_at"] = updated_at

    def _claim_job(self, params):
        status, queue_worker_id, device_locked_until, started_at, updated_at, job_id = params
        job = self._job_ref(job_id)
        job["status"] = status
        job["queue_worker_id"] = queue_worker_id
        job["device_locked_until"] = device_locked_until
        job["started_at"] = started_at
        job["updated_at"] = updated_at

    def _complete_job(self, params):
        status, finished_at, updated_at, job_id, expected_status = params
        job = self._job_ref(job_id)
        if job["status"] == expected_status:
            job["status"] = status
            job["finished_at"] = finished_at
            job["updated_at"] = updated_at

    def _fail_job(self, params):
        if len(params) == 5:
            status, error, finished_at, updated_at, job_id = params
            expected_status = None
        else:
            status, error, finished_at, updated_at, job_id, expected_status = params

        job = self._job_ref(job_id)
        if expected_status is None or job["status"] == expected_status:
            job["status"] = status
            job["error"] = error
            job["finished_at"] = finished_at
            job["updated_at"] = updated_at

    def _device_ref(self, device_id):
        for device in self.conn.devices:
            if device["id"] == device_id:
                return device
        raise AssertionError(f"device not found: {device_id}")

    def _job_ref(self, job_id):
        for job in self.conn.send_jobs:
            if job["id"] == job_id:
                return job
        raise AssertionError(f"send job not found: {job_id}")
