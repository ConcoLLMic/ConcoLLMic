#include <stdio.h>

int multiplier;

static bool
apply_suffix (double *x, char suffix_char)
{
  switch (suffix_char)
  {
    case 0:
    case 's':
      multiplier = 1;
      break;
    default:
      return false;
  }
  *x *= multiplier;
  return true;
}

int
main (int argc, char **argv)
{
  double seconds = 0.0;
  bool ok = true;

  for (int i = optind; i < argc; i++)
  {
    double s;
    char const *p;
    if (! (xstrtod (argv[i], &p, &s, cl_strtod) || errno == ERANGE)
        /* Nonnegative interval.  */
        || ! (0 <= s)
        /* No extra chars after the number and an optional s,m,h,d char.  */
        || (*p && *(p + 1))
        /* Check any suffix char and update S based on the suffix.  */
        || ! apply_suffix (&s, *p))
    {
      fprintf(stderr, "error: invalid time interval %s\n", argv[i]);
      ok = false;
    }

    seconds += s;
  }

  if (!ok)
    exit(1);

  xnanosleep (seconds);

  return EXIT_SUCCESS;
}