"""
CampusPoll Load Test
====================
Tests the platform under realistic election-day traffic.

Run locally:
    locust -f load_tests/locustfile.py --host=http://localhost:5000

Run headless (CI):
    locust -f load_tests/locustfile.py \
        --host=http://localhost:5000 \
        --users=50 --spawn-rate=5 \
        --run-time=60s --headless \
        --csv=load_tests/results

Benchmark targets (acceptable performance):
    - Homepage:        p95 < 200ms
    - Login:           p95 < 500ms
    - Dashboard:       p95 < 300ms
    - Vote:            p95 < 800ms
    - Results page:    p95 < 400ms
    - Analytics:       p95 < 1000ms
"""
from locust import HttpUser, task, between, events
import random
import string
import time


def random_email():
    return 'load_' + ''.join(random.choices(string.ascii_lowercase, k=8)) + '@test.com'


def random_sid():
    return 'LD' + ''.join(random.choices(string.digits, k=6))


class AnonymousUser(HttpUser):
    """Simulates unauthenticated visitors browsing the site."""
    wait_time = between(1, 3)
    weight = 2

    @task(5)
    def visit_homepage(self):
        self.client.get('/', name='Homepage')

    @task(3)
    def visit_login_page(self):
        self.client.get('/login', name='Login Page')

    @task(1)
    def visit_register_page(self):
        self.client.get('/register', name='Register Page')

    @task(1)
    def health_check(self):
        self.client.get('/health', name='Health Check')


class VoterUser(HttpUser):
    """Simulates a logged-in voter on election day."""
    wait_time = between(2, 5)
    weight = 10

    def on_start(self):
        """Register and log in before starting tasks."""
        self.email = random_email()
        self.password = 'Load@Test1'
        self.student_id = random_sid()
        self.election_id = None
        self.candidate_id = None
        self.voted = False

        # Register
        r = self.client.post('/register', data={
            'name': 'Load Test User',
            'email': self.email,
            'password': self.password,
            'student_id': self.student_id,
            'department': 'Computer Science',
            'year': '2nd Year',
        }, name='Register', catch_response=True)

        # Login
        r = self.client.post('/login', data={
            'email': self.email,
            'password': self.password,
        }, name='Login', catch_response=True)

        if r.status_code == 200 and 'Dashboard' in r.text:
            r.success()
        else:
            r.failure(f"Login failed: {r.status_code}")

    @task(8)
    def view_dashboard(self):
        self.client.get('/dashboard', name='Voter Dashboard')

    @task(5)
    def view_election_detail(self):
        if self.election_id:
            self.client.get(f'/election/{self.election_id}', name='Election Detail')

    @task(3)
    def cast_vote(self):
        if self.voted or not self.election_id or not self.candidate_id:
            return
        start = time.time()
        r = self.client.post(f'/vote/{self.election_id}',
            data={'candidate_id': self.candidate_id},
            name='Cast Vote', catch_response=True, allow_redirects=True)
        elapsed = (time.time() - start) * 1000
        if r.status_code == 200:
            self.voted = True
            if elapsed > 1000:
                r.failure(f"Vote too slow: {elapsed:.0f}ms")
            else:
                r.success()

    @task(2)
    def view_results(self):
        if self.election_id:
            self.client.get(f'/results/{self.election_id}', name='View Results')

    @task(1)
    def view_profile(self):
        self.client.get('/profile', name='Profile')

    @task(1)
    def view_nominations(self):
        self.client.get('/nominations', name='Nominations')

    @task(2)
    def check_notifications(self):
        self.client.get('/notifications/', name='Notifications API')


class AdminUser(HttpUser):
    """Simulates an admin managing the election."""
    wait_time = between(3, 8)
    weight = 1

    def on_start(self):
        self.client.post('/login', data={
            'email': 'admin@campuspoll.com',
            'password': 'Admin@123',
        }, name='Admin Login')

    @task(5)
    def view_dashboard(self):
        self.client.get('/admin/dashboard', name='Admin Dashboard')

    @task(3)
    def view_nominations(self):
        self.client.get('/admin/nominations', name='Admin Nominations')

    @task(2)
    def view_users(self):
        self.client.get('/admin/users', name='Admin Users')

    @task(2)
    def view_analytics(self):
        self.client.get('/analytics/dashboard', name='Analytics Dashboard')

    @task(1)
    def view_audit_log(self):
        self.client.get('/admin/audit-log', name='Audit Log')


@events.quitting.add_listener
def print_summary(environment, **kwargs):
    """Print performance summary when test ends."""
    print("\n=== CampusPoll Load Test Summary ===")
    stats = environment.runner.stats
    for name, stat in stats.entries.items():
        p95 = stat.get_response_time_percentile(0.95)
        print(f"{name[1]:40s} | p95: {p95:6.0f}ms | RPS: {stat.total_rps:.1f} | Fail%: {stat.fail_ratio*100:.1f}%")
