import { useEffect, useMemo, useState } from "react";
import { apiErrorMessage, branchesApi, usersApi } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  SearchInput,
  Select,
  Spinner,
  StatCard,
  TableShell,
  Tabs,
  Td,
  Th,
} from "../components/ui";

const emptyMember = {
  username: "",
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  role: "cashier",
  branch: "",
  password: "",
  confirm: "",
};

const emptyBranch = {
  name: "",
  code: "",
  address: "",
  phone: "",
  is_active: true,
};

function formatDate(value) {
  if (!value) return "Never";
  return new Date(value).toLocaleDateString("en-KE", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

export default function TeamScreen() {
  const { user, canManage, canManageUsers, branches, refreshWorkspace } = useAuth();
  const [tab, setTab] = useState("team");
  const effectiveTab = canManageUsers ? tab : "branches";
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(null);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");

  const [memberModal, setMemberModal] = useState(null);
  const [memberForm, setMemberForm] = useState(emptyMember);
  const [savingMember, setSavingMember] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState(null);
  const [passwordForm, setPasswordForm] = useState({ next: "", confirm: "" });
  const [savingPassword, setSavingPassword] = useState(false);

  const [branchModal, setBranchModal] = useState(null);
  const [branchForm, setBranchForm] = useState(emptyBranch);
  const [savingBranch, setSavingBranch] = useState(false);

  async function loadMembers() {
    setLoading(true);
    setError("");
    try {
      setMembers(await usersApi.list());
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load team members."));
      setMembers([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (canManageUsers) loadMembers();
  }, [canManageUsers]);

  const filteredMembers = useMemo(() => {
    const term = search.trim().toLowerCase();
    return members.filter((member) => {
      if (roleFilter && member.role !== roleFilter) return false;
      if (!term) return true;
      return [member.full_name, member.username, member.email, member.phone]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(term));
    });
  }, [members, search, roleFilter]);

  const managerCount = members.filter((member) => member.role === "manager" && member.is_active).length;
  const cashierCount = members.filter((member) => member.role === "cashier" && member.is_active).length;
  const inactiveCount = members.filter((member) => !member.is_active).length;

  function openCreateMember() {
    setMemberModal({ mode: "create" });
    setMemberForm({ ...emptyMember, branch: branches[0]?.id || "" });
    setNotice(null);
  }

  function openEditMember(member) {
    setMemberModal({ mode: "edit", member });
    setMemberForm({
      username: member.username,
      first_name: member.first_name || "",
      last_name: member.last_name || "",
      email: member.email || "",
      phone: member.phone || "",
      role: member.role,
      branch: member.branch?.id || "",
      password: "",
      confirm: "",
    });
    setNotice(null);
  }

  async function submitMember(event) {
    event.preventDefault();
    setNotice(null);
    const creating = memberModal.mode === "create";
    if (!memberForm.username.trim()) {
      setNotice({ tone: "error", message: "Enter a username for the account." });
      return;
    }
    if (creating && memberForm.password !== memberForm.confirm) {
      setNotice({ tone: "error", message: "The passwords do not match." });
      return;
    }
    if (creating && memberForm.password.length < 8) {
      setNotice({ tone: "error", message: "Set a password of at least 8 characters." });
      return;
    }
    setSavingMember(true);
    try {
      const base = {
        username: memberForm.username.trim(),
        first_name: memberForm.first_name.trim(),
        last_name: memberForm.last_name.trim(),
        email: memberForm.email.trim(),
        phone: memberForm.phone.trim(),
        role: memberForm.role,
        branch: memberForm.branch || null,
      };
      if (creating) {
        await usersApi.create({ ...base, password: memberForm.password });
        setNotice({ tone: "success", message: "Team member created. Share the password securely." });
      } else {
        await usersApi.update(memberModal.member.id, {
          ...base,
          is_active: memberModal.member.is_active,
        });
        setNotice({ tone: "success", message: "Team member updated." });
      }
      setMemberModal(null);
      await Promise.all([loadMembers(), refreshWorkspace()]);
    } catch (requestError) {
      setNotice({ tone: "error", message: apiErrorMessage(requestError, "Could not save the team member.") });
    } finally {
      setSavingMember(false);
    }
  }

  async function toggleActive(member) {
    const action = member.is_active ? "deactivate" : "reactivate";
    if (!window.confirm(`${action === "deactivate" ? "Deactivate" : "Reactivate"} ${member.full_name}?`)) {
      return;
    }
    setNotice(null);
    try {
      if (member.is_active) {
        await usersApi.deactivate(member.id);
      } else {
        await usersApi.update(member.id, { is_active: true });
      }
      setNotice({
        tone: "success",
        message: `${member.full_name} ${action === "deactivate" ? "cannot sign in anymore" : "can sign in again"}.`,
      });
      await loadMembers();
    } catch (requestError) {
      setNotice({ tone: "error", message: apiErrorMessage(requestError, "Could not update the account.") });
    }
  }

  async function submitPassword(event) {
    event.preventDefault();
    setNotice(null);
    if (passwordForm.next.length < 8) {
      setNotice({ tone: "error", message: "The new password must be at least 8 characters." });
      return;
    }
    if (passwordForm.next !== passwordForm.confirm) {
      setNotice({ tone: "error", message: "The passwords do not match." });
      return;
    }
    setSavingPassword(true);
    try {
      await usersApi.setPassword(passwordTarget.id, passwordForm.next);
      setNotice({
        tone: "success",
        message: `Password reset for ${passwordTarget.full_name}. They must sign in again with the new password.`,
      });
      setPasswordTarget(null);
      setPasswordForm({ next: "", confirm: "" });
      await loadMembers();
    } catch (requestError) {
      setNotice({ tone: "error", message: apiErrorMessage(requestError, "Could not reset the password.") });
    } finally {
      setSavingPassword(false);
    }
  }

  function openCreateBranch() {
    setBranchModal({ mode: "create" });
    setBranchForm(emptyBranch);
    setNotice(null);
  }

  function openEditBranch(branch) {
    setBranchModal({ mode: "edit", branch });
    setBranchForm({
      name: branch.name,
      code: branch.code,
      address: branch.address || "",
      phone: branch.phone || "",
      is_active: branch.is_active,
    });
    setNotice(null);
  }

  async function submitBranch(event) {
    event.preventDefault();
    setNotice(null);
    if (!branchForm.name.trim() || !branchForm.code.trim()) {
      setNotice({ tone: "error", message: "A branch needs a name and a short code." });
      return;
    }
    setSavingBranch(true);
    try {
      const payload = {
        name: branchForm.name.trim(),
        code: branchForm.code.trim().toUpperCase(),
        address: branchForm.address.trim(),
        phone: branchForm.phone.trim(),
        is_active: branchForm.is_active,
      };
      if (branchModal.mode === "create") {
        await branchesApi.create(payload);
      } else {
        await branchesApi.update(branchModal.branch.id, payload);
      }
      setBranchModal(null);
      setNotice({ tone: "success", message: "Branch saved." });
      await refreshWorkspace();
    } catch (requestError) {
      setNotice({ tone: "error", message: apiErrorMessage(requestError, "Could not save the branch.") });
    } finally {
      setSavingBranch(false);
    }
  }

  async function removeBranch(branch) {
    if (!window.confirm(`Delete branch ${branch.name}? Branches with records are deactivated instead.`)) {
      return;
    }
    setNotice(null);
    try {
      await branchesApi.remove(branch.id);
      setNotice({ tone: "success", message: "Branch deleted." });
      await refreshWorkspace();
    } catch (requestError) {
      setNotice({
        tone: "error",
        message: apiErrorMessage(
          requestError,
          "This branch has records and cannot be deleted. Deactivate it instead.",
        ),
      });
    }
  }

  if (!canManage) {
    return (
      <Alert tone="warning" title="Managers only">
        Managing branches is restricted to manager accounts. Super admin controls staff logins.
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Management"
        title={canManageUsers ? "Team & branches" : "Branches"}
        subtitle={
          canManageUsers
            ? "The super admin creates staff logins, resets passwords, and opens new shops."
            : "Open new shops and keep each branch's details up to date. Staff logins are managed by the super admin."
        }
        actions={
          effectiveTab === "team" ? (
            <Button icon="plus" onClick={openCreateMember}>
              Add team member
            </Button>
          ) : (
            <Button icon="plus" onClick={openCreateBranch}>
              Add branch
            </Button>
          )
        }
      />

      {notice && !memberModal && !passwordTarget && !branchModal && (
        <Alert tone={notice.tone} onClose={() => setNotice(null)}>
          {notice.message}
        </Alert>
      )}
      {error && (
        <Alert tone="error" title="Team unavailable" onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {canManageUsers && (
          <>
            <StatCard label="Active managers" value={managerCount} icon="shield" tone="brand" />
            <StatCard label="Active cashiers" value={cashierCount} icon="users" tone="info" />
            <StatCard label="Inactive logins" value={inactiveCount} icon="lock" tone="warning" />
          </>
        )}
        <StatCard label="Branches" value={branches.length} icon="store" tone="success" />
      </div>

      <Tabs
        items={
          canManageUsers
            ? [
                { id: "team", label: "Team logins", count: members.length },
                { id: "branches", label: "Branches", count: branches.length },
              ]
            : [{ id: "branches", label: "Branches", count: branches.length }]
        }
        value={effectiveTab}
        onChange={setTab}
        className="max-w-md"
      />

      {effectiveTab === "team" && canManageUsers ? (
        <Card>
          <CardHeader
            title="Staff accounts"
            subtitle="Managers can see everything and manage money. Cashiers record sales for their branch only."
            icon="users"
          />
          <div className="grid gap-3 px-5 pb-4 pt-4 sm:grid-cols-[minmax(0,1fr)_170px]">
            <SearchInput value={search} onChange={setSearch} placeholder="Search name, username or phone..." />
            <Select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
              <option value="">All roles</option>
              <option value="manager">Managers</option>
              <option value="cashier">Cashiers</option>
            </Select>
          </div>

          {loading ? (
            <Spinner label="Loading team" />
          ) : filteredMembers.length === 0 ? (
            <EmptyState
              icon="users"
              title="No team members match"
              message="Clear the filters or add a new cashier account."
              action={<Button icon="plus" onClick={openCreateMember}>Add team member</Button>}
            />
          ) : (
            <TableShell minWidth="880px">
              <thead>
                <tr>
                  <Th>Member</Th>
                  <Th>Role</Th>
                  <Th>Branch</Th>
                  <Th>Phone</Th>
                  <Th>Last login</Th>
                  <Th>Status</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {filteredMembers.map((member) => {
                  const isSelf = member.id === user?.id;
                  return (
                    <tr key={member.id} className="transition-colors hover:bg-ink-50/70">
                      <Td>
                        <div className="flex items-center gap-3">
                          <Avatar name={member.full_name || member.username} />
                          <div className="min-w-0">
                            <p className="truncate font-semibold text-ink-900">
                              {member.full_name || member.username}
                              {isSelf && <span className="ml-2 text-[10px] font-bold uppercase text-brand-700">you</span>}
                            </p>
                            <p className="truncate text-xs text-ink-400">
                              @{member.username}
                              {member.email ? ` · ${member.email}` : ""}
                            </p>
                          </div>
                        </div>
                      </Td>
                      <Td>
                        <Badge tone={member.role === "manager" ? "brand" : "neutral"}>
                          {member.role}
                        </Badge>
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-ink-500">
                        {member.branch?.name || "All branches"}
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-ink-500">{member.phone || "—"}</Td>
                      <Td className="whitespace-nowrap text-xs text-ink-500">{formatDate(member.last_login)}</Td>
                      <Td>
                        <Badge tone={member.is_active ? "success" : "danger"} dot>
                          {member.is_active ? "active" : "disabled"}
                        </Badge>
                      </Td>
                      <Td align="right">
                        <div className="flex justify-end gap-1">
                          <IconButton icon="edit" label="Edit member" onClick={() => openEditMember(member)} />
                          <IconButton
                            icon="lock"
                            label="Reset password"
                            onClick={() => {
                              setNotice(null);
                              setPasswordTarget(member);
                              setPasswordForm({ next: "", confirm: "" });
                            }}
                          />
                          {!isSelf && (
                            <IconButton
                              icon={member.is_active ? "trash" : "refresh"}
                              label={member.is_active ? "Deactivate member" : "Reactivate member"}
                              variant={member.is_active ? "dangerGhost" : "ghost"}
                              onClick={() => toggleActive(member)}
                            />
                          )}
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableShell>
          )}
        </Card>
      ) : (
        <Card>
          <CardHeader
            title="Shop branches"
            subtitle="Each branch keeps its own stock, receipts, cashiers and expenses. Reports can combine all branches."
            icon="store"
          />
          <div className="grid gap-4 px-5 pb-5 pt-4 sm:grid-cols-2 xl:grid-cols-3">
            {branches.map((branch) => (
              <div
                key={branch.id}
                className="rounded-2xl border border-ink-200/70 bg-ink-50/50 p-4"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-display text-base font-semibold text-ink-950">
                      {branch.name}
                    </p>
                    <p className="mt-0.5 text-xs font-bold uppercase tracking-wider text-ink-400">
                      {branch.code}
                    </p>
                  </div>
                  <Badge tone={branch.is_active ? "success" : "danger"} dot>
                    {branch.is_active ? "open" : "closed"}
                  </Badge>
                </div>
                <dl className="mt-4 space-y-1.5 text-sm">
                  <div className="flex justify-between gap-2">
                    <dt className="text-ink-400">Staff</dt>
                    <dd className="font-semibold text-ink-800">{branch.staff_count ?? 0}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-ink-400">Phone</dt>
                    <dd className="truncate font-medium text-ink-700">{branch.phone || "—"}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-ink-400">Address</dt>
                    <dd className="truncate font-medium text-ink-700">{branch.address || "—"}</dd>
                  </div>
                </dl>
                <div className="mt-4 flex gap-2">
                  <Button size="sm" variant="secondary" icon="edit" onClick={() => openEditBranch(branch)}>
                    Edit
                  </Button>
                  <Button size="sm" variant="dangerGhost" icon="trash" onClick={() => removeBranch(branch)}>
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Modal
        open={Boolean(memberModal)}
        onClose={() => setMemberModal(null)}
        title={memberModal?.mode === "edit" ? "Edit team member" : "Add team member"}
        subtitle="Only the super admin can create logins and issue passwords. Cashiers sell for their assigned branch."
        footer={
          <>
            <Button variant="secondary" onClick={() => setMemberModal(null)}>
              Cancel
            </Button>
            <Button type="submit" form="member-form" loading={savingMember}>
              {memberModal?.mode === "edit" ? "Save changes" : "Create account"}
            </Button>
          </>
        }
      >
        <form id="member-form" onSubmit={submitMember} className="space-y-3">
          {notice?.tone === "error" && <Alert tone="error">{notice.message}</Alert>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Username" required hint="Used to sign in. No spaces.">
              <Input
                value={memberForm.username}
                onChange={(event) => setMemberForm({ ...memberForm, username: event.target.value })}
                autoComplete="off"
                placeholder="e.g. faith"
              />
            </Field>
            <Field label="Phone">
              <Input
                value={memberForm.phone}
                onChange={(event) => setMemberForm({ ...memberForm, phone: event.target.value })}
                placeholder="07XX XXX XXX"
              />
            </Field>
            <Field label="First name">
              <Input
                value={memberForm.first_name}
                onChange={(event) => setMemberForm({ ...memberForm, first_name: event.target.value })}
              />
            </Field>
            <Field label="Last name">
              <Input
                value={memberForm.last_name}
                onChange={(event) => setMemberForm({ ...memberForm, last_name: event.target.value })}
              />
            </Field>
            <Field label="Email" className="sm:col-span-2">
              <Input
                type="email"
                value={memberForm.email}
                onChange={(event) => setMemberForm({ ...memberForm, email: event.target.value })}
              />
            </Field>
            <Field label="Role" required>
              <Select
                value={memberForm.role}
                onChange={(event) => setMemberForm({ ...memberForm, role: event.target.value })}
              >
                <option value="cashier">Cashier — sells for one branch</option>
                <option value="manager">Manager — full access</option>
              </Select>
            </Field>
            <Field label="Branch" hint="Cashiers are limited to this branch.">
              <Select
                value={memberForm.branch}
                onChange={(event) => setMemberForm({ ...memberForm, branch: event.target.value })}
              >
                <option value="">No fixed branch</option>
                {branches.map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name}
                  </option>
                ))}
              </Select>
            </Field>
            {memberModal?.mode === "create" && (
              <>
                <Field label="Password" required hint="At least 8 characters. Avoid common words.">
                  <Input
                    type="password"
                    value={memberForm.password}
                    onChange={(event) => setMemberForm({ ...memberForm, password: event.target.value })}
                    autoComplete="new-password"
                  />
                </Field>
                <Field label="Confirm password" required>
                  <Input
                    type="password"
                    value={memberForm.confirm}
                    onChange={(event) => setMemberForm({ ...memberForm, confirm: event.target.value })}
                    autoComplete="new-password"
                  />
                </Field>
              </>
            )}
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(passwordTarget)}
        onClose={() => {
          setPasswordTarget(null);
          setPasswordForm({ next: "", confirm: "" });
        }}
        title="Reset password"
        subtitle={passwordTarget ? `${passwordTarget.full_name} (@${passwordTarget.username})` : ""}
        size="sm"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                setPasswordTarget(null);
                setPasswordForm({ next: "", confirm: "" });
              }}
            >
              Cancel
            </Button>
            <Button type="submit" form="password-form" loading={savingPassword}>
              Reset password
            </Button>
          </>
        }
      >
        <form id="password-form" onSubmit={submitPassword} className="space-y-3">
          {notice?.tone === "error" && <Alert tone="error">{notice.message}</Alert>}
          <Alert tone="info">
            The member is signed out everywhere and must use the new password next time.
          </Alert>
          <Field label="New password" required hint="At least 8 characters.">
            <Input
              type="password"
              value={passwordForm.next}
              onChange={(event) => setPasswordForm({ ...passwordForm, next: event.target.value })}
              autoComplete="new-password"
              autoFocus
            />
          </Field>
          <Field label="Confirm new password" required>
            <Input
              type="password"
              value={passwordForm.confirm}
              onChange={(event) => setPasswordForm({ ...passwordForm, confirm: event.target.value })}
              autoComplete="new-password"
            />
          </Field>
        </form>
      </Modal>

      <Modal
        open={Boolean(branchModal)}
        onClose={() => setBranchModal(null)}
        title={branchModal?.mode === "edit" ? "Edit branch" : "Add branch"}
        subtitle="New branches get their own stock and receipts while sharing the same login system."
        footer={
          <>
            <Button variant="secondary" onClick={() => setBranchModal(null)}>
              Cancel
            </Button>
            <Button type="submit" form="branch-form" loading={savingBranch}>
              Save branch
            </Button>
          </>
        }
      >
        <form id="branch-form" onSubmit={submitBranch} className="space-y-3">
          {notice?.tone === "error" && <Alert tone="error">{notice.message}</Alert>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Branch name" required>
              <Input
                value={branchForm.name}
                onChange={(event) => setBranchForm({ ...branchForm, name: event.target.value })}
                placeholder="e.g. Town branch"
              />
            </Field>
            <Field label="Short code" required hint="Unique, e.g. TOWN or MAIN.">
              <Input
                value={branchForm.code}
                onChange={(event) => setBranchForm({ ...branchForm, code: event.target.value.toUpperCase() })}
                placeholder="TOWN"
              />
            </Field>
            <Field label="Phone">
              <Input
                value={branchForm.phone}
                onChange={(event) => setBranchForm({ ...branchForm, phone: event.target.value })}
              />
            </Field>
            <Field label="Address">
              <Input
                value={branchForm.address}
                onChange={(event) => setBranchForm({ ...branchForm, address: event.target.value })}
              />
            </Field>
            <Field label="Status" className="sm:col-span-2">
              <Select
                value={branchForm.is_active ? "active" : "closed"}
                onChange={(event) =>
                  setBranchForm({ ...branchForm, is_active: event.target.value === "active" })
                }
              >
                <option value="active">Open for business</option>
                <option value="closed">Closed</option>
              </Select>
            </Field>
          </div>
        </form>
      </Modal>
    </div>
  );
}
