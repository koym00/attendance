-- TEAMS
CREATE SEQUENCE IF NOT EXISTS public.teams_id_seq;
CREATE TABLE IF NOT EXISTS public.teams (
    id          integer NOT NULL DEFAULT nextval('public.teams_id_seq'),
    name        text COLLATE pg_catalog."default" NOT NULL,
    min_working integer NOT NULL DEFAULT 1,
    CONSTRAINT "Dochazka-TEAMS_pkey" PRIMARY KEY (id)
) TABLESPACE pg_default;
ALTER SEQUENCE public.teams_id_seq OWNED BY public.teams.id;
ALTER TABLE IF EXISTS public.teams OWNER TO "dochazka-collmng-db-test-owner";

-- MEMBERS
CREATE SEQUENCE IF NOT EXISTS public.members_id_seq;
CREATE TABLE IF NOT EXISTS public.members (
    id        integer NOT NULL DEFAULT nextval('public.members_id_seq'),
    name      text COLLATE pg_catalog."default" NOT NULL,
    allowance integer NOT NULL DEFAULT 200,
    fraction  double precision NOT NULL DEFAULT 1.0,
    cza       text COLLATE pg_catalog."default",
    CONSTRAINT "Dochazka-MEMBERS_pkey" PRIMARY KEY (id)
) TABLESPACE pg_default;
ALTER SEQUENCE public.members_id_seq OWNED BY public.members.id;
ALTER TABLE IF EXISTS public.members OWNER TO "dochazka-collmng-db-test-owner";

-- MEMBER_TEAMS
CREATE SEQUENCE IF NOT EXISTS public.member_teams_id_seq;
CREATE TABLE IF NOT EXISTS public.member_teams (
    id         integer NOT NULL DEFAULT nextval('public.member_teams_id_seq'),
    member_id  integer NOT NULL,
    team_id    integer NOT NULL,
    start_date text COLLATE pg_catalog."default",
    end_date   text COLLATE pg_catalog."default",
    CONSTRAINT "Dochazka-MEMBER_TEAMS_pkey" PRIMARY KEY (id),
    CONSTRAINT "Dochazka-MEMBER_TEAMS_member_id_fkey" FOREIGN KEY (member_id) REFERENCES public.members(id) ON DELETE CASCADE,
    CONSTRAINT "Dochazka-MEMBER_TEAMS_team_id_fkey" FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE
) TABLESPACE pg_default;
ALTER SEQUENCE public.member_teams_id_seq OWNED BY public.member_teams.id;
ALTER TABLE IF EXISTS public.member_teams OWNER TO "dochazka-collmng-db-test-owner";

-- ATTENDANCE
CREATE TABLE IF NOT EXISTS public.attendance (
    member_id integer NOT NULL,
    day       text COLLATE pg_catalog."default" NOT NULL,
    status    text COLLATE pg_catalog."default" NOT NULL,
    CONSTRAINT "Dochazka-ATTENDANCE_pkey" PRIMARY KEY (member_id, day),
    CONSTRAINT "Dochazka-ATTENDANCE_member_id_fkey" FOREIGN KEY (member_id) REFERENCES public.members(id) ON DELETE CASCADE
) TABLESPACE pg_default;
ALTER TABLE IF EXISTS public.attendance OWNER TO "dochazka-collmng-db-test-owner";

-- DUTY_SCHEDULES
CREATE SEQUENCE IF NOT EXISTS public.duty_schedules_id_seq;
CREATE TABLE IF NOT EXISTS public.duty_schedules (
    id          integer NOT NULL DEFAULT nextval('public.duty_schedules_id_seq'),
    team_id     integer NOT NULL,
    name        text COLLATE pg_catalog."default" NOT NULL DEFAULT 'Rotation',
    start_date  text COLLATE pg_catalog."default" NOT NULL,
    end_date    text COLLATE pg_catalog."default",
    period_days integer NOT NULL DEFAULT 7,
    active      integer NOT NULL DEFAULT 1,
    CONSTRAINT "Dochazka-DUTY_SCHEDULES_pkey" PRIMARY KEY (id),
    CONSTRAINT "Dochazka-DUTY_SCHEDULES_team_id_fkey" FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE
) TABLESPACE pg_default;
ALTER SEQUENCE public.duty_schedules_id_seq OWNED BY public.duty_schedules.id;
ALTER TABLE IF EXISTS public.duty_schedules OWNER TO "dochazka-collmng-db-test-owner";

-- DUTY_SLOTS
CREATE SEQUENCE IF NOT EXISTS public.duty_slots_id_seq;
CREATE TABLE IF NOT EXISTS public.duty_slots (
    id          integer NOT NULL DEFAULT nextval('public.duty_slots_id_seq'),
    schedule_id integer NOT NULL,
    day_offset  integer NOT NULL,
    member_id   integer,
    CONSTRAINT "Dochazka-DUTY_SLOTS_pkey" PRIMARY KEY (id),
    CONSTRAINT "Dochazka-DUTY_SLOTS_schedule_id_day_offset_key" UNIQUE (schedule_id, day_offset),
    CONSTRAINT "Dochazka-DUTY_SLOTS_schedule_id_fkey" FOREIGN KEY (schedule_id) REFERENCES public.duty_schedules(id) ON DELETE CASCADE,
    CONSTRAINT "Dochazka-DUTY_SLOTS_member_id_fkey" FOREIGN KEY (member_id) REFERENCES public.members(id) ON DELETE SET NULL
) TABLESPACE pg_default;
ALTER SEQUENCE public.duty_slots_id_seq OWNED BY public.duty_slots.id;
ALTER TABLE IF EXISTS public.duty_slots OWNER TO "dochazka-collmng-db-test-owner";

-- DUTY_REPLACEMENTS
CREATE SEQUENCE IF NOT EXISTS public.duty_replacements_id_seq;
CREATE TABLE IF NOT EXISTS public.duty_replacements (
    id          integer NOT NULL DEFAULT nextval('public.duty_replacements_id_seq'),
    team_id     integer NOT NULL,
    replacer_id integer NOT NULL,
    replaced_id integer,
    date        text COLLATE pg_catalog."default" NOT NULL,
    year        integer NOT NULL,
    manual      integer DEFAULT 0,
    CONSTRAINT "Dochazka-DUTY_REPLACEMENTS_pkey" PRIMARY KEY (id),
    CONSTRAINT "Dochazka-DUTY_REPLACEMENTS_team_id_date_key" UNIQUE (team_id, date),
    CONSTRAINT "Dochazka-DUTY_REPLACEMENTS_team_id_fkey" FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE,
    CONSTRAINT "Dochazka-DUTY_REPLACEMENTS_replacer_id_fkey" FOREIGN KEY (replacer_id) REFERENCES public.members(id) ON DELETE CASCADE,
    CONSTRAINT "Dochazka-DUTY_REPLACEMENTS_replaced_id_fkey" FOREIGN KEY (replaced_id) REFERENCES public.members(id) ON DELETE SET NULL
) TABLESPACE pg_default;
ALTER SEQUENCE public.duty_replacements_id_seq OWNED BY public.duty_replacements.id;
ALTER TABLE IF EXISTS public.duty_replacements OWNER TO "dochazka-collmng-db-test-owner";

-- MEMBER_ALLOWANCES
CREATE SEQUENCE IF NOT EXISTS public.member_allowances_id_seq;
CREATE TABLE IF NOT EXISTS public.member_allowances (
    id        integer NOT NULL DEFAULT nextval('public.member_allowances_id_seq'),
    member_id integer NOT NULL,
    year      integer NOT NULL,
    allowance integer NOT NULL,
    CONSTRAINT "Dochazka-MEMBER_ALLOWANCES_pkey" PRIMARY KEY (id),
    CONSTRAINT "Dochazka-MEMBER_ALLOWANCES_member_id_year_key" UNIQUE (member_id, year),
    CONSTRAINT "Dochazka-MEMBER_ALLOWANCES_member_id_fkey" FOREIGN KEY (member_id) REFERENCES public.members(id) ON DELETE CASCADE
) TABLESPACE pg_default;
ALTER SEQUENCE public.member_allowances_id_seq OWNED BY public.member_allowances.id;
ALTER TABLE IF EXISTS public.member_allowances OWNER TO "dochazka-collmng-db-test-owner";

CREATE TABLE IF NOT EXISTS public.duty_members (
    team_id   integer NOT NULL,
    member_id integer NOT NULL,
    CONSTRAINT duty_members_pkey PRIMARY KEY (team_id, member_id),
    CONSTRAINT duty_members_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE,
    CONSTRAINT duty_members_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id) ON DELETE CASCADE
) TABLESPACE pg_default;
ALTER TABLE IF EXISTS public.duty_members OWNER TO "dochazka-collmng-db-test-owner";
