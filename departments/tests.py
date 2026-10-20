from complaints.tests import Base


class DepartmentCategoryTests(Base):
    def test_categories_public_read_admin_write(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get("/api/categories/").status_code, 200)
        body = {"name": "Noise", "slug": "noise", "department": self.depts["General Review Department"].id, "sla_hours": 100}
        self.assertEqual(self.client_for(self.citizen).post("/api/categories/", body, format="json").status_code, 403)
        r = self.client_for(self.admin).post("/api/categories/", body, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.client_for(self.admin).patch(f"/api/categories/{r.data['id']}/", {"sla_hours": 50}, format="json").data["sla_hours"], 50)

    def test_department_writes_admin_only(self):
        body = {"name": "New Dept"}
        self.assertEqual(self.client_for(self.officer).post("/api/departments/", body, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.admin).post("/api/departments/", body, format="json").status_code, 201)

    def test_delete_category_with_complaints_deactivates(self):
        c = self.submitted()
        r = self.client_for(self.admin).delete(f"/api/categories/{c.category_id}/")
        self.assertEqual(r.status_code, 204)
        c.category.refresh_from_db()
        self.assertFalse(c.category.active)
