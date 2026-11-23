/-!
# Section 10 of `docs/access-and-operator-spec.md`, stated in Lean

Roles, capabilities, the table that says which role holds which, and the rule for who may
assume what. Core Lean 4 only. Check it with `lean formal/Access.lean` (no output means
every theorem holds).

This proves nothing about the Python. It is a second statement of the table, kept where a
compiler checks it for contradictions. It is run by hand; nothing in `make check` runs it.

Where the spec's table was not exact enough to write down, the choice made here is marked
`model:` and is listed in that document ("The Lean model of section 10").
-/

namespace Pauta

/-- A capability. The spec's table pairs some of them in one row (`work.read`, `work.write`);
they are separate here because a role may hold one half of a row. -/
inductive Cap
  | workRead | workWrite | workDelete
  | campaignsRead | campaignsWrite
  | financeRead | financeRecord | financeManage
  | integrationsRead
  | integrationsSync       -- model: "Atualizar agora", its own capability
  | integrationsReconnect  -- model: renew a connection that exists, its own capability
  | integrationsManage     -- connect, disconnect, link ad accounts
  | tenantSettings | membersManage | tenantExport
  deriving DecidableEq, Repr

inductive Role
  | member | admin | supportMasked | supportFull
  deriving DecidableEq, Repr

/-- The tenant's Financeiro setting (`finance_visible` in the code): off for everyone,
admins only, or everyone. -/
inductive Finance
  | off | admins | all
  deriving DecidableEq, Repr

open Cap Role Finance

/-- Is this one of the three `finance.*` capabilities? -/
def isFinance : Cap → Bool
  | financeRead | financeRecord | financeManage => true
  | _ => false

/-- The table. With Financeiro off nobody holds a `finance.*` capability, admins included. -/
def holds (fin : Finance) : Role → Cap → Bool
  | admin, c => !(isFinance c && fin == off)
  | member, workRead | member, workWrite | member, campaignsRead | member, campaignsWrite => true
  | member, financeRead | member, financeRecord => fin == all
  | member, _ => false
  | supportMasked, workRead | supportMasked, campaignsRead
  | supportMasked, integrationsRead | supportMasked, integrationsSync => true
  | supportMasked, _ => false
  | supportFull, workRead | supportFull, workWrite
  | supportFull, campaignsRead | supportFull, campaignsWrite
  | supportFull, integrationsRead
  | supportFull, integrationsSync  -- model: made explicit; the first table left it out
  | supportFull, integrationsReconnect => true
  | supportFull, financeRead => fin != off
  | supportFull, _ => false

/-- A capability that changes something. Everything else only reads. -/
def isWrite : Cap → Bool
  | workRead | campaignsRead | financeRead | integrationsRead => false
  | _ => true

/-! ## The role table -/

/-- "`admin` holds every capability `member` has." -/
theorem member_le_admin (fin : Finance) (c : Cap) :
    holds fin member c = true → holds fin admin c = true := by
  cases fin <;> cases c <;> decide

/-- "Full support holds everything masked support does." -/
theorem masked_le_full (fin : Finance) (c : Cap) :
    holds fin supportMasked c = true → holds fin supportFull c = true := by
  cases fin <;> cases c <;> decide

/-- "`support` is not in that line": each form holds something a member cannot. -/
theorem support_not_member_minus (fin : Finance) :
    holds fin supportMasked integrationsRead = true ∧ holds fin supportFull integrationsRead = true
      ∧ holds fin member integrationsRead = false := by
  cases fin <;> decide

/-- ...and masked support lacks something a member has, so it is not "member plus" either. -/
theorem support_not_member_plus (fin : Finance) :
    holds fin member workWrite = true ∧ holds fin supportMasked workWrite = false := by
  cases fin <;> decide

/-- No form of `support` deletes work, manages Financeiro, the integrations' wiring, the
settings or the members, or exports. -/
theorem support_never_manages (fin : Finance) (r : Role) (c : Cap) :
    (r = supportMasked ∨ r = supportFull) →
    (c = workDelete ∨ c = financeManage ∨ c = integrationsManage ∨ c = tenantSettings
      ∨ c = membersManage ∨ c = tenantExport) →
    holds fin r c = false := by
  intro hr hc
  rcases hr with rfl | rfl <;> rcases hc with rfl | rfl | rfl | rfl | rfl | rfl <;> rfl

/-- Masked support changes nothing but "Atualizar agora". -/
theorem masked_writes_only_sync (fin : Finance) (c : Cap) :
    holds fin supportMasked c = true → isWrite c = true → c = integrationsSync := by
  cases fin <;> cases c <;> decide

/-- With Financeiro off, no role holds a `finance.*` capability. -/
theorem finance_off_nobody (r : Role) (c : Cap) :
    isFinance c = true → holds off r c = false := by
  cases r <;> cases c <;> decide

/-- Masked support never sees money, whatever the tenant's setting. -/
theorem masked_no_finance (fin : Finance) :
    holds fin supportMasked financeRead = false ∧ holds fin supportMasked financeRecord = false
      ∧ holds fin supportMasked financeManage = false := by
  cases fin <;> decide

/-! ## Assuming a role -/

/-- What the actor is in this tenant before any assumption. -/
inductive Membership
  | none | member | admin
  deriving DecidableEq, Repr

/-- What a membership may do. No membership: nothing (the 404). -/
def Membership.holds (fin : Finance) : Membership → Cap → Bool
  | .none, _ => false
  | .member, c => Pauta.holds fin Role.member c
  | .admin, c => Pauta.holds fin Role.admin c

/-- Everything the rule reads about the actor and the moment. -/
structure Actor where
  membership : Membership
  owner : Bool    -- `account.owner`, set only by the CLI
  acting : Bool   -- an assumption is already active for this actor and tenant
  fresh : Bool    -- a passkey assertion made in the last five minutes
  reason : Bool   -- a reason was given
  grant : Bool    -- one of the tenant's admins granted full support, and the grant has not expired

/-- The rule. An admin may look as a member; only the owner may assume `support`; nothing
starts under another assumption; nobody assumes `admin`. -/
def mayAssume (a : Actor) : Role → Bool
  | member => !a.acting && a.membership == .admin
  | admin => false
  | supportMasked => !a.acting && a.owner && a.fresh && a.reason
  | supportFull => !a.acting && a.owner && a.fresh && a.reason && a.grant

/-- "No chaining": nothing can be assumed while an assumption is active. -/
theorem no_chaining (a : Actor) (r : Role) : a.acting = true → mayAssume a r = false := by
  intro h
  cases r <;> simp [mayAssume, h]

/-- Nobody assumes `admin`. -/
theorem admin_never_assumed (a : Actor) : mayAssume a admin = false := rfl

/-- "Only the owner may assume `support`." -/
theorem only_owner_assumes_support (a : Actor) (r : Role) :
    (r = supportMasked ∨ r = supportFull) → mayAssume a r = true → a.owner = true := by
  intro hr h
  rcases hr with rfl | rfl <;> simp [mayAssume] at h <;> simp [h]

/-- `support` always takes a passkey tap made just now and a reason. -/
theorem support_needs_fresh_and_reason (a : Actor) (r : Role) :
    (r = supportMasked ∨ r = supportFull) → mayAssume a r = true →
    a.fresh = true ∧ a.reason = true := by
  intro hr h
  rcases hr with rfl | rfl <;> simp [mayAssume] at h <;> simp [h]

/-- Full `support` needs a tenant admin's grant. -/
theorem full_needs_grant (a : Actor) : mayAssume a supportFull = true → a.grant = true := by
  intro h
  simp [mayAssume] at h
  simp [h]

/-- "Never upward": someone who is not the owner ends an assumption with a subset of what
their membership gave them. (For the owner, `support` is a different set, not a smaller
one: see `support_not_member_minus`.) -/
theorem never_upward (fin : Finance) (a : Actor) (r : Role) (c : Cap) :
    a.owner = false → mayAssume a r = true → holds fin r c = true →
    a.membership.holds fin c = true := by
  intro ho h hc
  cases r <;> simp [mayAssume, ho] at h
  -- the only case left is `member`, assumed by an admin
  have hadmin := member_le_admin fin c hc
  simpa [Membership.holds, h.2] using hadmin

/-- A stranger (no membership, not the owner) can assume nothing. -/
theorem stranger_assumes_nothing (a : Actor) (r : Role) :
    a.membership = .none → a.owner = false → mayAssume a r = false := by
  intro hm ho
  cases r <;> simp [mayAssume, hm, ho]

/-! ## The one rule: actor and effective role -/

/-- What a request carries. -/
structure Ctx where
  actor : Nat             -- the account whose passkey signed in
  role : Role             -- what the request may do in this tenant
  asAccount : Option Nat  -- "ver como <pessoa>"

/-- Starting an assumption. It can set the role and `asAccount`; there is no way to say
"and the actor becomes". -/
def assume (ctx : Ctx) (r : Role) (as : Option Nat) : Ctx :=
  { ctx with role := r, asAccount := as }

/-- "The actor never changes." -/
theorem actor_unchanged (ctx : Ctx) (r : Role) (as : Option Nat) :
    (assume ctx r as).actor = ctx.actor := rfl

/-! ## Viewing as a person -/

/-- What a request may do: the role's capabilities, minus every write while viewing as a
person. model: under `support` with `asAccount`, the capabilities stay `support`'s (so the
masking stays), not the person's. -/
def effective (fin : Finance) (ctx : Ctx) (c : Cap) : Bool :=
  holds fin ctx.role c && !(ctx.asAccount.isSome && isWrite c)

/-- "Read-only. Any write under `as_account` is a 403." -/
theorem view_as_read_only (fin : Finance) (ctx : Ctx) (c : Cap) :
    ctx.asAccount.isSome = true → effective fin ctx c = true → isWrite c = false := by
  intro has h
  simp [effective, has] at h
  exact h.2

/-- Viewing as a person never adds a capability. -/
theorem view_as_never_adds (fin : Finance) (ctx : Ctx) (c : Cap) :
    effective fin ctx c = true → holds fin ctx.role c = true := by
  intro h
  simp [effective] at h
  exact h.1

/-- Who may be viewed by a member of the tenant: "an admin, as a person with a lower role". -/
def mayViewAs (viewer target : Membership) : Bool :=
  viewer == .admin && target == .member

/-- "Never as an admin from below", and never as someone who is not in the tenant. -/
theorem view_as_only_downward (viewer target : Membership) :
    mayViewAs viewer target = true → viewer = .admin ∧ target = .member := by
  cases viewer <;> cases target <;> decide

end Pauta
