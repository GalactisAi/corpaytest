import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../ui/card';
import { Button } from '../../ui/button';
import { Input } from '../../ui/input';
import { Label } from '../../ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../../ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../ui/table';
import { FileUpload } from '../FileUpload';
import { toast } from 'sonner';
import { Plus, Edit, Trash2, Upload, ImageIcon, ChevronDown } from 'lucide-react';
import axios from 'axios';
import { api } from '@/app/services/api';

interface Employee {
  id: string;
  name: string;
  milestone: string;
  description: string;
  photoUrl?: string;
  date: string;
}

const MILESTONE_EMOJI: Record<string, string> = {
  'Work Anniversary': '📅',
  'Promotion': '📈',
  'Birthday': '🎂',
  'Achievement': '🏆',
  'New Hire': '✨',
};

function MilestoneSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);

  const label =
    value && MILESTONE_EMOJI[value]
      ? `${MILESTONE_EMOJI[value]} ${value}`
      : 'Select milestone...';

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="employee-milestone-select w-full flex items-center justify-between px-3 py-2 rounded-md border border-white/20 bg-[rgba(45,20,30,0.85)] text-white"
      >
        <span className="truncate">{label}</span>
        <ChevronDown className="w-4 h-4 text-white ml-2 flex-shrink-0" />
      </button>
      {open && (
        <div className="absolute left-0 right-0 mt-1 rounded-md border border-white/20 bg-[#2d141e] text-sm text-[#e0e0e0] shadow-lg z-50 max-h-56 overflow-y-auto">
          {Object.entries(MILESTONE_EMOJI).map(([milestoneLabel, emoji]) => (
            <button
              key={milestoneLabel}
              type="button"
              onClick={() => {
                onChange(milestoneLabel);
                setOpen(false);
              }}
              className={`w-full text-left px-3 py-2 flex items-center gap-2 ${
                value === milestoneLabel ? 'bg-[#5b1b2e] text-white' : 'hover:bg-[#3d1628]'
              }`}
            >
              <span>{emoji}</span>
              <span className="truncate">{milestoneLabel}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function EmployeesPage() {
  const [employees, setEmployees] = useState<Employee[]>([]);

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    milestone: '',
    description: '',
    photoUrl: '',
    date: ''
  });

  // Load employees from API on mount
  useEffect(() => {
    fetchEmployees();
  }, []);

  const fetchEmployees = async () => {
    try {
      const token = localStorage.getItem('authToken') || localStorage.getItem('token');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      const response = await api.get('admin/employees', { headers, timeout: 120000 });
      const employeesData = response.data || [];
      // Transform backend format to UI format
      const transformedEmployees = employeesData.map((emp: any) => ({
        id: emp.id.toString(),
        name: emp.name,
        milestone: emp.milestone_type === 'anniversary' ? 'Work Anniversary' :
                   emp.milestone_type === 'promotion' ? 'Promotion' :
                   emp.milestone_type === 'achievement' ? 'Achievement' :
                   emp.milestone_type === 'birthday' ? 'Birthday' :
                   emp.milestone_type === 'new_hire' ? 'New Hire' : emp.milestone_type,
        description: emp.description,
        photoUrl: emp.avatar_path || '',
        date: emp.milestone_date ? new Date(emp.milestone_date).toISOString().split('T')[0] : ''
      }));
      setEmployees(transformedEmployees);
    } catch (error) {
      console.error('Error fetching employees:', error);
    }
  };

  const handleSubmit = async () => {
    if (!formData.name || !formData.milestone || !formData.description || !formData.date) {
      toast.error('Please fill in all fields');
      return;
    }

    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    const milestoneTypeMap: Record<string, string> = {
      'Work Anniversary': 'anniversary',
      'Promotion': 'promotion',
      'Birthday': 'birthday',
      'Achievement': 'achievement',
      'New Hire': 'new_hire'
    };

    let avatarPath = formData.photoUrl || null;

    if (photoFile && token) {
      try {
        const formDataUpload = new FormData();
        formDataUpload.append('file', photoFile);
        formDataUpload.append('employee_id', '0');
        const uploadResponse = await api.post('admin/employees/upload-photo', formDataUpload, {
          headers: { Authorization: `Bearer ${token}` },
          timeout: 120000,
        });
        avatarPath = uploadResponse.data?.avatar_path ?? avatarPath;
      } catch (uploadError: any) {
        console.error('Photo upload error:', uploadError);
        toast.error('Failed to upload photo. Continuing without photo.');
      }
    }

    const milestoneData = {
      name: formData.name,
      description: formData.description,
      avatar_path: avatarPath,
      border_color: '#981239',
      background_color: '#fef5f8',
      milestone_type: milestoneTypeMap[formData.milestone] || 'anniversary',
      department: null,
      milestone_date: new Date(formData.date).toISOString()
    };

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      let response;
      if (editingEmployee) {
        const milestoneId = editingEmployee.id;
        try {
          response = await api.put(`admin/employees/${milestoneId}`, milestoneData, { headers, timeout: 120000 });
        } catch (putError: any) {
          if (putError.response?.status === 405) {
            response = await api.patch(`admin/employees/${milestoneId}`, milestoneData, { headers, timeout: 120000 });
          } else {
            throw putError;
          }
        }
        if (photoFile && response?.data?.id) {
          const formDataUpload = new FormData();
          formDataUpload.append('file', photoFile);
          formDataUpload.append('employee_id', response.data.id.toString());
          try {
            await api.post('admin/employees/upload-photo', formDataUpload, {
              headers: { Authorization: `Bearer ${token}` },
              timeout: 120000,
            });
          } catch (uploadError: any) {
            console.error('Photo upload on update failed:', uploadError);
          }
        }
      } else {
        response = await api.post('admin/employees', milestoneData, { headers, timeout: 120000 });
        if (photoFile && response?.data?.id && !avatarPath) {
          const formDataUpload = new FormData();
          formDataUpload.append('file', photoFile);
          formDataUpload.append('employee_id', response.data.id.toString());
          try {
            const uploadResponse = await api.post('admin/employees/upload-photo', formDataUpload, {
              headers: token ? { Authorization: `Bearer ${token}` } : {},
              timeout: 120000,
            });
            avatarPath = uploadResponse.data?.avatar_path;
          } catch (uploadError: any) {
            console.error('Photo upload after creation failed:', uploadError);
          }
        }
      }

      toast.success(editingEmployee ? 'Employee milestone updated successfully' : 'Employee milestone saved successfully to backend');
      handleDialogClose();
      fetchEmployees();
    } catch (error: any) {
      console.error('Error saving employee:', error);
      const errorMessage = error.response?.data?.detail || error.message || 'Network Error';
      if (error.code === 'ECONNREFUSED' || error.message?.includes('Network Error') || !error.response) {
        toast.error('Failed to save: Cannot connect to backend. Is the backend running?');
      } else {
        toast.error(`Failed to save: ${errorMessage}`);
      }
    }
  };

  const handleDelete = async (id: string) => {
    const token = localStorage.getItem('authToken') || localStorage.getItem('token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      await api.delete(`admin/employees/${id}`, { headers, timeout: 120000 });
      toast.success('Employee milestone deleted successfully');
      fetchEmployees();
    } catch (error: any) {
      console.error('Error deleting employee:', error);
      toast.error(`Failed to delete: ${error.response?.data?.detail || error.message}`);
    }
  };

  const handleEdit = (employee: Employee) => {
    setEditingEmployee(employee);
    setFormData({
      name: employee.name,
      milestone: employee.milestone,
      description: employee.description,
      photoUrl: employee.photoUrl || '',
      date: employee.date
    });
    setIsDialogOpen(true);
  };

  const handleDialogClose = () => {
    setIsDialogOpen(false);
    setEditingEmployee(null);
    setFormData({ name: '', milestone: '', description: '', photoUrl: '', date: '' });
    setPhotoFile(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl text-white mb-2">Employee Milestones</h1>
          <p className="text-gray-400">Manage employee achievements and milestones</p>
        </div>
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger asChild>
            <Button className="bg-pink-600 hover:bg-pink-700">
              <Plus className="w-4 h-4 mr-2" />
              Add Employee
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[#3d0f1f] border-white/20 text-white max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editingEmployee ? 'Edit Employee' : 'Add New Employee'}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              <div className="space-y-2">
                <Label>Employee Name</Label>
                <Input
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="John Doe"
                  className="bg-white/10 border-white/20 text-white"
                />
              </div>

              <div className="space-y-2">
                <Label>Milestone Type</Label>
                <MilestoneSelect
                  value={formData.milestone}
                  onChange={(milestone) => setFormData({ ...formData, milestone })}
                />
              </div>

              <div className="space-y-2">
                <Label>Description</Label>
                <Input
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="10 Years in Finance"
                  className="bg-white/10 border-white/20 text-white"
                />
              </div>

              <div className="space-y-2">
                <Label>Date</Label>
                <Input
                  type="date"
                  value={formData.date}
                  onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                  className="bg-white/10 border-white/20 text-white"
                />
              </div>

              <FileUpload
                selectedFile={photoFile}
                onFileSelect={setPhotoFile}
                onClear={() => setPhotoFile(null)}
                accept={{
                  'image/*': ['.png', '.jpg', '.jpeg', '.gif']
                }}
                label="Employee Photo"
                theme="dark"
              />

              <div className="flex gap-2 justify-end">
                <Button variant="outline" onClick={handleDialogClose} className="border-white/20">
                  Cancel
                </Button>
                <Button onClick={handleSubmit} className="bg-pink-600 hover:bg-pink-700">
                  {editingEmployee ? 'Update' : 'Add'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <Card className="bg-white/10 border-white/20">
        <CardHeader>
          <CardTitle className="text-white">All Employee Milestones</CardTitle>
          <CardDescription className="text-gray-400">
            {employees.length} total milestones
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow className="border-white/10 hover:bg-white/5">
                <TableHead className="text-gray-300">Name</TableHead>
                <TableHead className="text-gray-300">Milestone</TableHead>
                <TableHead className="text-gray-300">Description</TableHead>
                <TableHead className="text-gray-300">Date</TableHead>
                <TableHead className="text-gray-300 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {employees.map((employee) => (
                <TableRow key={employee.id} className="border-white/10 hover:bg-white/5">
                  <TableCell className="text-white">{employee.name}</TableCell>
                  <TableCell>
                    <span className="px-2 py-1 rounded text-xs bg-purple-500/20 text-purple-300">
                      {MILESTONE_EMOJI[employee.milestone] ? `${MILESTONE_EMOJI[employee.milestone]} ` : ''}{employee.milestone}
                    </span>
                  </TableCell>
                  <TableCell className="text-gray-400">{employee.description}</TableCell>
                  <TableCell className="text-gray-400">{employee.date}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex gap-2 justify-end">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleEdit(employee)}
                        className="text-gray-400 hover:text-white"
                      >
                        <Edit className="w-4 h-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleDelete(employee.id)}
                        className="text-red-400 hover:text-red-300"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
